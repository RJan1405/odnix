from django.db.models import Count, F, ExpressionWrapper, FloatField, Case, When, Value, IntegerField
from django.db.models.functions import Now, Cast
from django.utils import timezone
from .models import Reel, Follow


class ContentRecommender:
    """
    Recommendation Engine for Odnix.
    Implements a weighted scoring algorithm inspired by social media ranking signals.
    """

    def __init__(self, user):
        self.user = user

    def get_reels(self, limit=50):
        """
        Get recommended reels for the user based on:
        1. Engagement (Likes, Comments, Views)
        2. Freshness (Time decay)
        3. Affinity (Following status)
        """
        # 1. Get IDs of users the current user follows
        if self.user.is_authenticated:
            following_ids = list(Follow.objects.filter(
                follower=self.user).values_list('following_id', flat=True))
        else:
            following_ids = []

        # 2. Annotate Reels with signals
        # We calculate a 'rank_score'.
        # Note: SQLite date math can be tricky, so we'll use a simplified freshness approach
        # or do precise math if using PostgreSQL. For widespread compatibility,
        # we will fetch candidate posts and rank in Python if the dataset is small,
        # OR use robust Django expressions.

        # Let's use a Hybrid: Filter for candidates -> Rank in Python (safer for complex scoring on SQLite)

        # Candidate Generation: Get recent reels (e.g., last 30 days) to keep query fast
        cutoff = timezone.now() - timezone.timedelta(days=30)
        candidates = Reel.objects.filter(created_at__gte=cutoff).select_related(
            'user').prefetch_related('likes', 'comments')

        # We can annotate counts effectively in DB
        candidates = candidates.annotate(
            num_likes=Count('likes'),
            num_comments=Count('comments')
        )

        ranked_reels = []
        now = timezone.now()
        import random

        for reel in candidates:
            score = 0

            # --- SIGNAL 1: POPULARITY (Engagement) ---
            # Weights: Likes (2.0), Comments (4.0), Views (0.1)
            engagement_score = (reel.num_likes * 2.0) + \
                (reel.num_comments * 4.0) + (reel.views_count * 0.1)
            score += engagement_score

            # --- SIGNAL 2: FRESHNESS (Time Decay) ---
            # Newer posts get significantly higher scores.
            # Formula: 1000 / (hours_old + 2)^1.8
            age_in_hours = (now - reel.created_at).total_seconds() / 3600
            freshness_score = 1000 / ((age_in_hours + 2) ** 1.8)
            score += freshness_score

            # --- SIGNAL 3: AFFINITY (Relationship) ---
            # If user follows the creator, give a massive boost (e.g., +50)
            if reel.user_id in following_ids:
                score += 50

            # --- SIGNAL 4: SERENDIPITY (Random Jitter) ---
            # Randomize score broadly (0-400 points) to ensure feed variety on every refresh.
            # This high variance ensures that even lower-ranked reels have a chance to jump to the top.
            score += random.uniform(0, 400)

            # If it's your own reel, give it a slight boost so you see it,
            # or penalty if you want to hide own content. Let's boost slightly for confirmation.
            if reel.user_id == self.user.id:
                score += 10

            ranked_reels.append((reel, score))

        # Sort by score descending
        ranked_reels.sort(key=lambda x: x[1], reverse=True)

        # Deduplicate: Keep track of seen reel IDs to avoid duplicates
        seen_ids = set()
        unique_reels = []
        for reel, score in ranked_reels:
            if reel.id not in seen_ids:
                seen_ids.add(reel.id)
                unique_reels.append(reel)
                if len(unique_reels) >= limit:
                    break

        # Return only the Reel objects, capped by limit
        return unique_reels

    def get_explore_feed(self, limit=100):
        """
        Get trending content for Explore page (ignoring follow status).
        """
        # Similar logic but without Affinity boost
        pass
