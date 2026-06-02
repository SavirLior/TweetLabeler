import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

try:
    from . import twitter_crawler
    from .twitter_crawler import (
        build_discovered_tweets_from_items,
        calculate_overfetch_limit,
        read_keywords_file,
        write_final_jihadi_users_file,
    )
except ImportError:
    import twitter_crawler
    from twitter_crawler import (
        build_discovered_tweets_from_items,
        calculate_overfetch_limit,
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
