import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

try:
    from . import twitter_crawler
    from .twitter_crawler import (
        TweetEvaluation,
        build_discovered_tweets_from_items,
        calculate_overfetch_limit,
        is_deep_dive_trigger,
        read_keywords_file,
        write_final_jihadi_users_file,
    )
except ImportError:
    import twitter_crawler
    from twitter_crawler import (
        TweetEvaluation,
        build_discovered_tweets_from_items,
        calculate_overfetch_limit,
        is_deep_dive_trigger,
        read_keywords_file,
        write_final_jihadi_users_file,
    )


class TwitterCrawlerHelperTests(unittest.TestCase):
    def test_profile_overfetch_limit_uses_one_point_five_multiplier(self):
        self.assertEqual(calculate_overfetch_limit(100, 1.5), 150)

    def test_profile_collection_keeps_all_valid_tweets_from_raw_fetch(self):
        items = [
            {
                "id": str(index),
                "lang": "en",
                "author": {"userName": "ExampleUser"},
                "fullText": f"Valid profile tweet number {index}",
            }
            for index in range(137)
        ]

        result = build_discovered_tweets_from_items(items, scope="profile")

        self.assertEqual(len(result.tweets), 137)
        self.assertEqual(result.counts["raw_profile_tweets_seen"], 137)

    def test_training_users_are_filtered_case_insensitively(self):
        original_training_usernames = twitter_crawler._training_usernames
        twitter_crawler._training_usernames = {"ysimmunye", "exampleuser"}
        try:
            items = [
                {
                    "id": "1",
                    "lang": "en",
                    "author": {"userName": "ExampleUser"},
                    "fullText": "This user is already in training.",
                },
                {
                    "id": "2",
                    "lang": "en",
                    "author": {"userName": "FreshUser"},
                    "fullText": "This user is new enough to keep.",
                },
            ]

            result = build_discovered_tweets_from_items(items, scope="discovery")

            self.assertEqual([tweet.username for tweet in result.tweets], ["FreshUser"])
            self.assertEqual(result.counts["filtered_training_user"], 1)
            self.assertTrue(twitter_crawler.is_training_user("@//YsiMmunye"))
        finally:
            twitter_crawler._training_usernames = original_training_usernames

    def test_deep_dive_trigger_includes_jihadi_and_taklidi_tweets(self):
        jihadi = TweetEvaluation(
            tweet="jihadi",
            label="Salafi jihadi",
            flagged=True,
            confidence=0.9,
            probabilities={},
        )
        taklidi = TweetEvaluation(
            tweet="taklidi",
            label="Salafi taklidi",
            flagged=False,
            confidence=0.9,
            probabilities={},
        )
        irrelevant = TweetEvaluation(
            tweet="irrelevant",
            label="Irrelevant",
            flagged=False,
            confidence=0.9,
            probabilities={},
        )

        self.assertTrue(is_deep_dive_trigger(jihadi))
        self.assertTrue(is_deep_dive_trigger(taklidi))
        self.assertFalse(is_deep_dive_trigger(irrelevant))

    def test_compact_source_includes_author_location_and_influence_metrics(self):
        items = [
            {
                "id": "123",
                "lang": "en",
                "author": {
                    "userName": "ExampleUser",
                    "location": "London",
                    "followersCount": "12,345",
                    "followingCount": 500,
                    "statusesCount": 9000,
                    "isVerified": True,
                },
                "fullText": "A profile tweet with metrics.",
                "likeCount": 10,
                "replyCount": 2,
                "retweetCount": 3,
                "quoteCount": 1,
                "viewCount": "1,200",
                "bookmarkCount": 4,
            }
        ]

        result = build_discovered_tweets_from_items(items, scope="profile")

        source = result.tweets[0].source
        self.assertEqual(source["author"]["location"], "London")
        self.assertEqual(source["author"]["followers_count"], 12345)
        self.assertEqual(source["author"]["following_count"], 500)
        self.assertEqual(source["author"]["tweet_count"], 9000)
        self.assertTrue(source["author"]["verified"])
        self.assertEqual(source["like_count"], 10)
        self.assertEqual(source["reply_count"], 2)
        self.assertEqual(source["retweet_count"], 3)
        self.assertEqual(source["quote_count"], 1)
        self.assertEqual(source["view_count"], 1200)
        self.assertEqual(source["bookmark_count"], 4)

    def test_keywords_file_ignores_comments_blanks_and_duplicates(self):
        with TemporaryDirectory() as directory:
            keywords_path = Path(directory) / "keywords.txt"
            keywords_path.write_text(
                "# ignored\n\nfirst keyword\nFirst Keyword\nsecond keyword\n",
                encoding="utf-8",
            )

            self.assertEqual(
                read_keywords_file(keywords_path),
                ["first keyword", "second keyword"],
            )

    def test_final_jihadi_users_file_writes_sorted_normalized_usernames(self):
        with TemporaryDirectory() as directory:
            output_path = Path(directory) / "final_jihadi_users.txt"

            write_final_jihadi_users_file(
                ["@BetaUser", "alphaUser", "@betauser"],
                output_path,
            )

            self.assertEqual(
                output_path.read_text(encoding="utf-8").splitlines(),
                ["alphaUser", "BetaUser"],
            )


if __name__ == "__main__":
    unittest.main()
