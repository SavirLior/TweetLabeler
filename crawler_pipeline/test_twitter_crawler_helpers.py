import unittest

try:
    from .twitter_crawler import build_discovered_tweets_from_items, calculate_overfetch_limit
except ImportError:
    from twitter_crawler import build_discovered_tweets_from_items, calculate_overfetch_limit


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


if __name__ == "__main__":
    unittest.main()
