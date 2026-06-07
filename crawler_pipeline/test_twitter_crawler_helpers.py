import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

try:
    from . import twitter_crawler
    from .twitter_crawler import (
        DiscoveredTweet,
        TweetEvaluation,
        TweetCollectionResult,
        build_discovered_tweets_from_items,
        calculate_overfetch_limit,
        is_deep_dive_trigger,
        read_keywords_file,
        run_pipeline,
        write_final_jihadi_users_file,
    )
except ImportError:
    import twitter_crawler
    from twitter_crawler import (
        DiscoveredTweet,
        TweetEvaluation,
        TweetCollectionResult,
        build_discovered_tweets_from_items,
        calculate_overfetch_limit,
        is_deep_dive_trigger,
        read_keywords_file,
        run_pipeline,
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


class TwitterCrawlerPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_pipeline_skips_deep_dive_when_user_already_scanned_with_model(self):
        class FakeStore:
            def __init__(self):
                self.finished_counts = None
                self.saved_users = []

            def start_run(self, *, keywords, params, run_id=None):
                return "run-1"

            def has_user_run_for_model(self, username, model_info):
                return username == "AlreadyScanned"

            def save_user_deep_dive(self, **kwargs):
                self.saved_users.append(kwargs["username"])
                return {
                    "status": "not_salafi_jihadi",
                    "score": {},
                    "evidence_count": 0,
                }

            def finish_run(self, run_id, *, counts, errors=None, status="completed"):
                self.finished_counts = dict(counts)

        original_build_client = twitter_crawler.build_apify_client
        original_discover = twitter_crawler.discover_tweet_collection_by_keywords
        original_evaluate = twitter_crawler.evaluate_tweets_with_fusion_model
        original_verify = twitter_crawler.verify_user_from_triggered_tweet
        original_model_info = twitter_crawler.get_configured_model_info

        fake_store = FakeStore()
        verify_called = False

        def fake_discover(*args, **kwargs):
            return TweetCollectionResult(
                tweets=[
                    DiscoveredTweet(
                        username="AlreadyScanned",
                        text="trigger tweet",
                        tweet_key="x:1",
                    )
                ],
                counts={},
            )

        async def fake_evaluate(*args, **kwargs):
            return [
                TweetEvaluation(
                    tweet="trigger tweet",
                    label="Salafi jihadi",
                    flagged=True,
                    confidence=0.9,
                    probabilities={},
                )
            ]

        async def fake_verify(*args, **kwargs):
            nonlocal verify_called
            verify_called = True
            raise AssertionError("Deep dive should be skipped")

        try:
            twitter_crawler.build_apify_client = lambda: object()
            twitter_crawler.discover_tweet_collection_by_keywords = fake_discover
            twitter_crawler.evaluate_tweets_with_fusion_model = fake_evaluate
            twitter_crawler.verify_user_from_triggered_tweet = fake_verify
            twitter_crawler.get_configured_model_info = lambda: {
                "model_export_dir": "model_export_exp_88_iter_181",
                "iteration_id": 181,
                "model_name": "181",
            }

            result = await run_pipeline(["term"], mongo_store=fake_store)

            self.assertEqual(result, {})
            self.assertFalse(verify_called)
            self.assertEqual(fake_store.saved_users, [])
            self.assertEqual(fake_store.finished_counts["triggered_users"], 1)
            self.assertEqual(fake_store.finished_counts["triggered_tweets"], 1)
            self.assertEqual(fake_store.finished_counts["skipped_existing_model_users"], 1)
            self.assertEqual(
                fake_store.finished_counts["skipped_existing_model_triggered_tweets"],
                1,
            )
            self.assertEqual(fake_store.finished_counts["deep_dived_users"], 0)
        finally:
            twitter_crawler.build_apify_client = original_build_client
            twitter_crawler.discover_tweet_collection_by_keywords = original_discover
            twitter_crawler.evaluate_tweets_with_fusion_model = original_evaluate
            twitter_crawler.verify_user_from_triggered_tweet = original_verify
            twitter_crawler.get_configured_model_info = original_model_info


if __name__ == "__main__":
    unittest.main()
