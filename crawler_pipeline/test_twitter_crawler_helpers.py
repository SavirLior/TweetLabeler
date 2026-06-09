import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

try:
    from . import twitter_crawler
    from .twitter_crawler import (
        DiscoveredTweet,
        TweetEvaluation,
        TweetCollectionResult,
        build_discovered_tweet,
        build_discovered_tweets_from_items,
        calculate_overfetch_limit,
        extract_author_id,
        is_deep_dive_trigger,
        is_self_reply,
        merge_self_reply_threads,
        parse_tweet_timestamp,
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
        build_discovered_tweet,
        build_discovered_tweets_from_items,
        calculate_overfetch_limit,
        extract_author_id,
        is_deep_dive_trigger,
        is_self_reply,
        merge_self_reply_threads,
        parse_tweet_timestamp,
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

    def test_deep_dive_trigger_requires_high_confidence_jihadi_tweet(self):
        high_confidence_jihadi = TweetEvaluation(
            tweet="jihadi",
            label="Salafi jihadi",
            flagged=True,
            confidence=0.9,
            probabilities={"Salafi jihadi": 0.71, "Salafi taklidi": 0.2},
        )
        threshold_jihadi = TweetEvaluation(
            tweet="threshold jihadi",
            label="Salafi jihadi",
            flagged=True,
            confidence=0.7,
            probabilities={"Salafi jihadi": 0.70, "Salafi taklidi": 0.2},
        )
        low_confidence_jihadi = TweetEvaluation(
            tweet="low jihadi",
            label="Salafi jihadi",
            flagged=True,
            confidence=0.69,
            probabilities={"Salafi jihadi": 0.69, "Salafi taklidi": 0.2},
        )
        taklidi = TweetEvaluation(
            tweet="taklidi",
            label="Salafi taklidi",
            flagged=False,
            confidence=0.9,
            probabilities={"Salafi jihadi": 0.05, "Salafi taklidi": 0.9},
        )
        irrelevant = TweetEvaluation(
            tweet="irrelevant",
            label="Irrelevant",
            flagged=False,
            confidence=0.9,
            probabilities={"Salafi jihadi": 0.05, "Irrelevant": 0.9},
        )

        self.assertTrue(is_deep_dive_trigger(high_confidence_jihadi))
        self.assertFalse(is_deep_dive_trigger(threshold_jihadi))
        self.assertFalse(is_deep_dive_trigger(low_confidence_jihadi))
        self.assertFalse(is_deep_dive_trigger(taklidi))
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
    class FakeStore:
        def __init__(self):
            self.finished_counts = None
            self.saved_users = []

        def start_run(self, *, keywords, params, run_id=None):
            return "run-1"

        def has_user_run_for_model(self, username, model_info):
            return False

        def save_user_deep_dive(self, **kwargs):
            self.saved_users.append(kwargs["username"])
            return {
                "status": "not_salafi_jihadi",
                "score": {},
                "evidence_count": 0,
            }

        def finish_run(self, run_id, *, counts, errors=None, status="completed"):
            self.finished_counts = dict(counts)

    async def test_run_pipeline_does_not_deep_dive_on_taklidi_discovery_tweet(self):
        fake_store = self.FakeStore()
        original_build_client = twitter_crawler.build_apify_client
        original_discover = twitter_crawler.discover_tweet_collection_by_keywords
        original_evaluate = twitter_crawler.evaluate_tweets_with_fusion_model
        original_verify = twitter_crawler.verify_user_from_triggered_tweet

        async def fake_evaluate(texts, batch_size=16):
            return [
                TweetEvaluation(
                    tweet=texts[0],
                    label="Salafi taklidi",
                    flagged=False,
                    confidence=0.95,
                    probabilities={
                        "Salafi jihadi": 0.01,
                        "Salafi taklidi": 0.95,
                    },
                )
            ]

        async def fail_verify(*args, **kwargs):
            raise AssertionError("Taklidi discovery tweets must not trigger deep dive.")

        try:
            twitter_crawler.build_apify_client = lambda: object()
            twitter_crawler.discover_tweet_collection_by_keywords = (
                lambda *args, **kwargs: TweetCollectionResult(
                    tweets=[
                        DiscoveredTweet(
                            username="TaklidiUser",
                            text="taklidi discovery text",
                            tweet_key="x:1",
                        )
                    ],
                    counts={
                        "raw_discovery_tweets_seen": 1,
                        "model_discovery_tweets_evaluated": 1,
                    },
                )
            )
            twitter_crawler.evaluate_tweets_with_fusion_model = fake_evaluate
            twitter_crawler.verify_user_from_triggered_tweet = fail_verify

            result = await twitter_crawler.run_pipeline(
                ["keyword"],
                mongo_store=fake_store,
            )

            self.assertEqual(result, {})
            self.assertEqual(fake_store.saved_users, [])
            self.assertEqual(fake_store.finished_counts["triggered_tweets"], 0)
            self.assertEqual(fake_store.finished_counts["triggered_users"], 0)
            self.assertEqual(fake_store.finished_counts["deep_dived_users"], 0)
        finally:
            twitter_crawler.build_apify_client = original_build_client
            twitter_crawler.discover_tweet_collection_by_keywords = original_discover
            twitter_crawler.evaluate_tweets_with_fusion_model = original_evaluate
            twitter_crawler.verify_user_from_triggered_tweet = original_verify

    async def test_run_pipeline_skips_deep_dive_when_user_already_scanned_with_model(self):
        class ExistingModelStore(self.FakeStore):
            def has_user_run_for_model(self, username, model_info):
                return username == "AlreadyScanned"

        fake_store = ExistingModelStore()
        verify_called = False
        original_build_client = twitter_crawler.build_apify_client
        original_discover = twitter_crawler.discover_tweet_collection_by_keywords
        original_evaluate = twitter_crawler.evaluate_tweets_with_fusion_model
        original_verify = twitter_crawler.verify_user_from_triggered_tweet
        original_model_info = twitter_crawler.get_configured_model_info

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
                    probabilities={"Salafi jihadi": 0.9},
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
            self.assertEqual(
                fake_store.finished_counts["skipped_existing_model_users"],
                1,
            )
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


class ThreadReconstructionTests(unittest.TestCase):

    def _make_item(self, tweet_id, author_id, text, *, is_reply=False,
                   in_reply_to_id=None, in_reply_to_user_id=None,
                   conversation_id=None, created_at=None, retweet=None):
        item = {
            "id": tweet_id,
            "text": text,
            "fullText": text,
            "lang": "en",
            "author": {"id": author_id, "userName": f"user_{author_id}"},
            "isReply": is_reply,
        }
        if in_reply_to_id:
            item["inReplyToId"] = in_reply_to_id
        if in_reply_to_user_id:
            item["inReplyToUserId"] = in_reply_to_user_id
        if conversation_id:
            item["conversationId"] = conversation_id
        if created_at:
            item["createdAt"] = created_at
        if retweet:
            item["retweet"] = retweet
        return item

    def test_extract_author_id(self):
        self.assertEqual(extract_author_id({"author": {"id": "123"}}), "123")
        self.assertEqual(extract_author_id({"author": {"userId": "456"}}), "456")
        self.assertIsNone(extract_author_id({"author": {}}))
        self.assertIsNone(extract_author_id({}))

    def test_is_self_reply_matching_author(self):
        item = self._make_item("101", "999", "part 2", is_reply=True,
                               in_reply_to_user_id="999")
        self.assertTrue(is_self_reply(item))

    def test_is_self_reply_different_author(self):
        item = self._make_item("101", "999", "reply to other", is_reply=True,
                               in_reply_to_user_id="888")
        self.assertFalse(is_self_reply(item))

    def test_is_self_reply_not_a_reply(self):
        item = self._make_item("100", "999", "standalone", is_reply=False)
        self.assertFalse(is_self_reply(item))

    def test_is_self_reply_retweet_excluded(self):
        item = self._make_item("101", "999", "RT text", is_reply=True,
                               in_reply_to_user_id="999",
                               retweet={"text": "retweeted content"})
        self.assertFalse(is_self_reply(item))

    def test_parse_tweet_timestamp_twitter_format(self):
        ts = parse_tweet_timestamp({"createdAt": "Mon Jan 01 12:00:00 +0000 2024"})
        self.assertIsNotNone(ts)
        self.assertEqual(ts.year, 2024)

    def test_parse_tweet_timestamp_iso_format(self):
        ts = parse_tweet_timestamp({"createdAt": "2024-01-01T12:00:00.000Z"})
        self.assertIsNotNone(ts)
        self.assertEqual(ts.year, 2024)

    def test_parse_tweet_timestamp_missing(self):
        self.assertIsNone(parse_tweet_timestamp({}))

    def test_merge_two_part_thread(self):
        items = [
            self._make_item("100", "999", "Part 1 of thread",
                            conversation_id="100",
                            created_at="Mon Jan 01 12:00:00 +0000 2024"),
            self._make_item("101", "999", "Part 2 continues here", is_reply=True,
                            in_reply_to_id="100", in_reply_to_user_id="999",
                            conversation_id="100",
                            created_at="Mon Jan 01 12:02:00 +0000 2024"),
        ]
        merged = merge_self_reply_threads(items)
        self.assertEqual(len(merged), 1)
        self.assertTrue(merged[0]["_is_merged_thread"])
        self.assertEqual(merged[0]["_thread_length"], 2)
        self.assertIn("Part 1", merged[0]["fullText"])
        self.assertIn("Part 2", merged[0]["fullText"])

    def test_merge_three_part_thread(self):
        items = [
            self._make_item("100", "999", "Part 1",
                            conversation_id="100",
                            created_at="Mon Jan 01 12:00:00 +0000 2024"),
            self._make_item("101", "999", "Part 2", is_reply=True,
                            in_reply_to_id="100", in_reply_to_user_id="999",
                            conversation_id="100",
                            created_at="Mon Jan 01 12:01:00 +0000 2024"),
            self._make_item("102", "999", "Part 3", is_reply=True,
                            in_reply_to_id="101", in_reply_to_user_id="999",
                            conversation_id="100",
                            created_at="Mon Jan 01 12:03:00 +0000 2024"),
        ]
        merged = merge_self_reply_threads(items)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["_thread_length"], 3)
        self.assertEqual(merged[0]["_thread_tweet_ids"], ["100", "101", "102"])

    def test_standalone_tweets_pass_through(self):
        items = [
            self._make_item("300", "777", "Hello world"),
            self._make_item("301", "777", "Another tweet"),
        ]
        result = merge_self_reply_threads(items)
        self.assertEqual(len(result), 2)
        self.assertFalse(any(i.get("_is_merged_thread") for i in result))

    def test_time_gap_splits_chain(self):
        items = [
            self._make_item("200", "888", "Part 1",
                            conversation_id="200",
                            created_at="Mon Jan 01 12:00:00 +0000 2024"),
            self._make_item("201", "888", "Part 2", is_reply=True,
                            in_reply_to_id="200", in_reply_to_user_id="888",
                            conversation_id="200",
                            created_at="Mon Jan 01 12:03:00 +0000 2024"),
            self._make_item("202", "888", "Comment hours later", is_reply=True,
                            in_reply_to_id="201", in_reply_to_user_id="888",
                            conversation_id="200",
                            created_at="Mon Jan 01 15:00:00 +0000 2024"),
        ]
        merged = merge_self_reply_threads(items)
        self.assertEqual(len(merged), 2)
        thread_items = [i for i in merged if i.get("_is_merged_thread")]
        standalone_items = [i for i in merged if not i.get("_is_merged_thread")]
        self.assertEqual(len(thread_items), 1)
        self.assertEqual(len(standalone_items), 1)
        self.assertEqual(thread_items[0]["_thread_length"], 2)

    def test_missing_timestamp_falls_back_to_standalone(self):
        items = [
            self._make_item("400", "555", "Part 1",
                            conversation_id="400"),
            self._make_item("401", "555", "Part 2", is_reply=True,
                            in_reply_to_id="400", in_reply_to_user_id="555",
                            conversation_id="400"),
        ]
        merged = merge_self_reply_threads(items)
        self.assertEqual(len(merged), 2)
        self.assertFalse(any(i.get("_is_merged_thread") for i in merged))

    def test_thread_head_missing_from_results(self):
        items = [
            self._make_item("501", "666", "Part 2 only", is_reply=True,
                            in_reply_to_id="500", in_reply_to_user_id="666",
                            conversation_id="500",
                            created_at="Mon Jan 01 12:02:00 +0000 2024"),
        ]
        merged = merge_self_reply_threads(items)
        self.assertEqual(len(merged), 1)
        self.assertFalse(merged[0].get("_is_merged_thread"))

    def test_cross_user_replies_not_merged(self):
        items = [
            self._make_item("600", "111", "Original tweet",
                            conversation_id="600",
                            created_at="Mon Jan 01 12:00:00 +0000 2024"),
            self._make_item("601", "222", "Reply from different user", is_reply=True,
                            in_reply_to_id="600", in_reply_to_user_id="111",
                            conversation_id="600",
                            created_at="Mon Jan 01 12:01:00 +0000 2024"),
        ]
        merged = merge_self_reply_threads(items)
        self.assertEqual(len(merged), 2)
        self.assertFalse(any(i.get("_is_merged_thread") for i in merged))

    def test_build_discovered_tweet_from_merged_item(self):
        items = [
            self._make_item("700", "444", "Part 1 text here",
                            conversation_id="700",
                            created_at="Mon Jan 01 12:00:00 +0000 2024"),
            self._make_item("701", "444", "Part 2 continues", is_reply=True,
                            in_reply_to_id="700", in_reply_to_user_id="444",
                            conversation_id="700",
                            created_at="Mon Jan 01 12:01:00 +0000 2024"),
        ]
        merged = merge_self_reply_threads(items)
        dt = build_discovered_tweet(merged[0])
        self.assertIsNotNone(dt)
        self.assertTrue(dt.is_merged_thread)
        self.assertEqual(dt.thread_length, 2)
        self.assertEqual(dt.thread_tweet_ids, ["700", "701"])
        self.assertEqual(dt.source_text_kind, "thread")
        self.assertIn("Part 1", dt.text)
        self.assertIn("Part 2", dt.text)

    def test_mixed_threads_and_standalone(self):
        items = [
            self._make_item("800", "333", "Standalone tweet 1"),
            self._make_item("810", "333", "Thread part 1",
                            conversation_id="810",
                            created_at="Mon Jan 01 12:00:00 +0000 2024"),
            self._make_item("811", "333", "Thread part 2", is_reply=True,
                            in_reply_to_id="810", in_reply_to_user_id="333",
                            conversation_id="810",
                            created_at="Mon Jan 01 12:01:00 +0000 2024"),
            self._make_item("820", "333", "Standalone tweet 2"),
        ]
        merged = merge_self_reply_threads(items)
        self.assertEqual(len(merged), 3)
        thread_items = [i for i in merged if i.get("_is_merged_thread")]
        self.assertEqual(len(thread_items), 1)


if __name__ == "__main__":
    unittest.main()
