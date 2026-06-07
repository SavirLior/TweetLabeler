import unittest

try:
    from .mongo_store import (
        CrawlerMongoStore,
        EVIDENCE_COLLECTION,
        RUNS_COLLECTION,
        STATUS_NOT_SALAFI_JIHADI,
        STATUS_SALAFI_JIHADI,
        STATUS_SALAFI_TAKLIDI,
        STATUS_INSUFFICIENT_DATA,
        USER_RUNS_COLLECTION,
        USERS_COLLECTION,
        aggregate_user_influence,
        calculate_classification_score,
        calculate_influence_score,
    )
except ImportError:
    from mongo_store import (
        CrawlerMongoStore,
        EVIDENCE_COLLECTION,
        RUNS_COLLECTION,
        STATUS_NOT_SALAFI_JIHADI,
        STATUS_SALAFI_JIHADI,
        STATUS_SALAFI_TAKLIDI,
        STATUS_INSUFFICIENT_DATA,
        USER_RUNS_COLLECTION,
        USERS_COLLECTION,
        aggregate_user_influence,
        calculate_classification_score,
        calculate_influence_score,
    )


class FakeUpdateResult:
    def __init__(self, matched_count=0, upserted_id=None):
        self.matched_count = matched_count
        self.upserted_id = upserted_id


class FakeCollection:
    def __init__(self):
        self.docs = []
        self.indexes = []

    def create_index(self, *args, **kwargs):
        self.indexes.append((args, kwargs))

    def count_documents(self, filter_doc, limit=0):
        matched_count = 0
        for doc in self.docs:
            if self._matches(doc, filter_doc):
                matched_count += 1
                if limit and matched_count >= limit:
                    return matched_count
        return matched_count

    def update_one(self, filter_doc, update_doc, upsert=False):
        for doc in self.docs:
            if self._matches(doc, filter_doc):
                self._apply_update(doc, update_doc, inserted=False)
                return FakeUpdateResult(matched_count=1)

        if not upsert:
            return FakeUpdateResult()

        doc = dict(filter_doc)
        self._apply_update(doc, update_doc, inserted=True)
        self.docs.append(doc)
        return FakeUpdateResult(upserted_id=len(self.docs))

    @staticmethod
    def _matches(doc, filter_doc):
        for key, value in filter_doc.items():
            if key == "$or":
                if not any(FakeCollection._matches(doc, option) for option in value):
                    return False
                continue
            if FakeCollection._get_nested(doc, key) != value:
                return False
        return True

    @staticmethod
    def _get_nested(doc, dotted_key):
        value = doc
        for key in dotted_key.split("."):
            if not isinstance(value, dict):
                return None
            value = value.get(key)
        return value

    @staticmethod
    def _apply_update(doc, update_doc, *, inserted):
        if inserted:
            doc.update(update_doc.get("$setOnInsert", {}))

        doc.update(update_doc.get("$set", {}))
        for key in update_doc.get("$unset", {}):
            doc.pop(key, None)

        for key, add_to_set_value in update_doc.get("$addToSet", {}).items():
            current_values = doc.setdefault(key, [])
            values_to_add = add_to_set_value.get("$each", [add_to_set_value])
            for value in values_to_add:
                if value not in current_values:
                    current_values.append(value)


class FakeDb:
    def __init__(self):
        self.collections = {}

    def __getitem__(self, name):
        if name not in self.collections:
            self.collections[name] = FakeCollection()
        return self.collections[name]


def evidence_docs(total, positive, *, taklidi=0, offset=0):
    docs = []
    for index in range(total):
        flagged = index < positive
        is_taklidi = positive <= index < positive + taklidi
        model_label = (
            "Salafi jihadi"
            if flagged
            else "Salafi taklidi"
            if is_taklidi
            else "Irrelevant"
        )
        tweet_number = index + offset
        docs.append(
            {
                "tweet_key": f"x:{tweet_number}",
                "text": f"tweet {tweet_number}",
                "model_label": model_label,
                "flagged": flagged,
                "confidence": 0.9 if flagged else 0.8,
                "source": {
                    "provider": "apify",
                    "tweet_id": str(tweet_number),
                    "author": {"username": "ExampleUser"},
                },
                "probabilities": {
                    "Salafi jihadi": 0.9 if flagged else 0.1,
                    "Salafi taklidi": 0.9 if is_taklidi else 0.1,
                    "Irrelevant": 0.1 if flagged or is_taklidi else 0.9,
                },
            }
        )
    return docs


class CrawlerMongoStoreTests(unittest.TestCase):
    def test_classification_threshold_uses_more_than_ten_percent_and_minimum_profile_size(self):
        ninety_nine_with_many_positive = calculate_classification_score(
            evidence_docs(99, 20),
            positive_ratio_threshold=0.10,
            min_positive_tweets=10,
            min_evaluated_tweets=100,
        )
        self.assertEqual(ninety_nine_with_many_positive["status"], STATUS_INSUFFICIENT_DATA)

        ten_of_one_hundred = calculate_classification_score(
            evidence_docs(100, 10),
            positive_ratio_threshold=0.10,
            min_positive_tweets=10,
            min_evaluated_tweets=100,
        )
        self.assertEqual(ten_of_one_hundred["status"], STATUS_NOT_SALAFI_JIHADI)

        eleven_of_one_hundred = calculate_classification_score(
            evidence_docs(100, 11),
            positive_ratio_threshold=0.10,
            min_positive_tweets=10,
            min_evaluated_tweets=100,
        )
        self.assertEqual(eleven_of_one_hundred["status"], STATUS_SALAFI_JIHADI)

    def test_classification_can_mark_taklidi_when_ratio_clears_threshold_and_margin(self):
        twenty_five_percent = calculate_classification_score(
            evidence_docs(100, 10, taklidi=25),
            positive_ratio_threshold=0.50,
            min_positive_tweets=999,
            min_evaluated_tweets=100,
        )
        self.assertEqual(twenty_five_percent["status"], STATUS_NOT_SALAFI_JIHADI)

        too_close_to_jihadi_ratio = calculate_classification_score(
            evidence_docs(100, 24, taklidi=30),
            positive_ratio_threshold=0.50,
            min_positive_tweets=999,
            min_evaluated_tweets=100,
        )
        self.assertEqual(too_close_to_jihadi_ratio["status"], STATUS_NOT_SALAFI_JIHADI)

        clears_threshold_and_margin = calculate_classification_score(
            evidence_docs(100, 24, taklidi=31),
            positive_ratio_threshold=0.50,
            min_positive_tweets=999,
            min_evaluated_tweets=100,
        )
        self.assertEqual(clears_threshold_and_margin["status"], STATUS_SALAFI_TAKLIDI)
        self.assertEqual(clears_threshold_and_margin["taklidi_count"], 31)
        self.assertAlmostEqual(clears_threshold_and_margin["taklidi_ratio"], 0.31)

    def test_taklidi_classification_takes_priority_over_jihadi(self):
        score = calculate_classification_score(
            evidence_docs(100, 30, taklidi=40),
            positive_ratio_threshold=0.10,
            min_positive_tweets=1,
            min_evaluated_tweets=100,
        )

        self.assertEqual(score["status"], STATUS_SALAFI_TAKLIDI)

    def test_aggregate_user_influence_uses_author_profile_and_tweet_metrics(self):
        docs = evidence_docs(2, 1)
        docs[0]["source"].update(
            {
                "author": {
                    "username": "ExampleUser",
                    "location": "London",
                    "description": "Profile bio",
                    "followers_count": 1000,
                    "following_count": 200,
                    "tweet_count": 3000,
                    "verified": True,
                },
                "view_count": 100,
                "like_count": 10,
                "reply_count": 2,
                "retweet_count": 3,
                "quote_count": 1,
                "bookmark_count": 5,
            }
        )
        docs[1]["source"].update(
            {
                "author": {
                    "username": "ExampleUser",
                    "followers_count": 1200,
                    "following_count": 250,
                    "tweet_count": 3200,
                },
                "view_count": 50,
                "like_count": 4,
                "reply_count": 1,
                "retweet_count": 2,
                "quote_count": 0,
                "bookmark_count": 1,
            }
        )

        influence = aggregate_user_influence(docs)

        self.assertEqual(influence["location"], "London")
        self.assertEqual(influence["description"], "Profile bio")
        self.assertEqual(influence["followers_count"], 1200)
        self.assertEqual(influence["following_count"], 250)
        self.assertEqual(influence["tweet_count"], 3200)
        self.assertTrue(influence["verified"])
        self.assertEqual(influence["views_count"], 150)
        self.assertEqual(influence["likes_count"], 14)
        self.assertEqual(influence["replies_count"], 3)
        self.assertEqual(influence["retweets_count"], 5)
        self.assertEqual(influence["quotes_count"], 1)
        self.assertEqual(influence["shares_count"], 6)
        self.assertEqual(influence["bookmarks_count"], 6)
        self.assertEqual(influence["engagement_count"], 23)
        self.assertEqual(influence["influence_score"], calculate_influence_score(influence))
        self.assertGreater(influence["influence_score"], 0)

    def test_save_user_deep_dive_writes_only_crawler_collections_and_is_idempotent(self):
        fake_db = FakeDb()
        store = CrawlerMongoStore(db=fake_db)
        thresholds = {
            "positive_ratio_threshold": 0.12,
            "min_positive_tweets": 8,
            "min_profile_evaluated_tweets": 4,
        }
        model_info = {
            "model_name": "181",
            "model_export_dir": "model_export_exp_88_iter_181",
            "iteration_id": 181,
        }
        store.start_run(keywords=["term"], params=thresholds, run_id="run-1")

        trigger = evidence_docs(1, 1)
        profile = evidence_docs(4, 3, offset=100)
        store.save_user_deep_dive(
            run_id="run-1",
            username="@ExampleUser",
            trigger_evidence=trigger,
            profile_evidence=profile,
            keywords=["term"],
            thresholds=thresholds,
            model_info=model_info,
        )
        store.save_user_deep_dive(
            run_id="run-1",
            username="@ExampleUser",
            trigger_evidence=trigger,
            profile_evidence=profile,
            keywords=["term"],
            thresholds=thresholds,
            model_info=model_info,
        )

        self.assertEqual(
            set(fake_db.collections),
            {RUNS_COLLECTION, USERS_COLLECTION, USER_RUNS_COLLECTION, EVIDENCE_COLLECTION},
        )
        self.assertEqual(len(fake_db[USERS_COLLECTION].docs), 1)
        self.assertEqual(len(fake_db[USER_RUNS_COLLECTION].docs), 1)
        self.assertEqual(len(fake_db[EVIDENCE_COLLECTION].docs), 5)
        self.assertEqual(fake_db[USERS_COLLECTION].docs[0]["latest_model"], model_info)
        self.assertEqual(fake_db[USER_RUNS_COLLECTION].docs[0]["model"], model_info)
        evidence_doc = fake_db[EVIDENCE_COLLECTION].docs[0]
        self.assertEqual(evidence_doc["source"]["provider"], "apify")
        self.assertNotIn("raw_apify_item", evidence_doc)
        self.assertNotIn("tweets", fake_db.collections)
        self.assertNotIn("users", fake_db.collections)

    def test_latest_user_status_updates_while_user_run_history_is_preserved(self):
        fake_db = FakeDb()
        store = CrawlerMongoStore(db=fake_db)
        thresholds = {
            "positive_ratio_threshold": 0.12,
            "min_positive_tweets": 8,
            "min_profile_evaluated_tweets": 4,
        }

        store.start_run(keywords=["first"], params=thresholds, run_id="run-1")
        store.save_user_deep_dive(
            run_id="run-1",
            username="ExampleUser",
            trigger_evidence=evidence_docs(1, 1),
            profile_evidence=evidence_docs(8, 8, offset=100),
            keywords=["first"],
            thresholds=thresholds,
        )

        store.start_run(keywords=["second"], params=thresholds, run_id="run-2")
        store.save_user_deep_dive(
            run_id="run-2",
            username="ExampleUser",
            trigger_evidence=evidence_docs(1, 1),
            profile_evidence=evidence_docs(9, 1, offset=200),
            keywords=["second"],
            thresholds=thresholds,
        )

        user_doc = fake_db[USERS_COLLECTION].docs[0]
        self.assertEqual(user_doc["latest_run_id"], "run-2")
        self.assertEqual(user_doc["current_status"], STATUS_NOT_SALAFI_JIHADI)
        self.assertEqual(len(fake_db[USER_RUNS_COLLECTION].docs), 2)

    def test_has_user_run_for_model_matches_username_iteration_and_export(self):
        fake_db = FakeDb()
        store = CrawlerMongoStore(db=fake_db)
        thresholds = {
            "positive_ratio_threshold": 0.12,
            "min_positive_tweets": 8,
            "min_profile_evaluated_tweets": 4,
        }
        model_181 = {
            "model_export_dir": "model_export_exp_88_iter_181",
            "iteration_id": 181,
            "model_name": "181",
        }
        model_180 = {
            "model_export_dir": "model_export_exp_87_iter_180",
            "iteration_id": 180,
            "model_name": "180",
        }

        store.start_run(keywords=["term"], params={"model": model_181}, run_id="run-1")
        store.save_user_deep_dive(
            run_id="run-1",
            username="@ExampleUser",
            trigger_evidence=evidence_docs(1, 1),
            profile_evidence=evidence_docs(4, 3, offset=100),
            keywords=["term"],
            thresholds=thresholds,
            model_info=model_181,
        )

        self.assertTrue(store.has_user_run_for_model("exampleuser", model_181))
        self.assertTrue(
            store.has_user_run_for_model(
                "ExampleUser",
                {
                    "model_export_dir": "model_export_exp_88_iter_181",
                    "iteration": 181,
                },
            )
        )
        self.assertFalse(store.has_user_run_for_model("ExampleUser", model_180))
        self.assertFalse(store.has_user_run_for_model("FreshUser", model_181))
        self.assertFalse(
            store.has_user_run_for_model(
                "ExampleUser",
                {"model_export_dir": "model_export_exp_88_iter_181"},
            )
        )

    def test_trigger_evidence_does_not_affect_profile_score(self):
        fake_db = FakeDb()
        store = CrawlerMongoStore(db=fake_db)
        thresholds = {
            "positive_ratio_threshold": 0.12,
            "min_positive_tweets": 8,
            "min_profile_evaluated_tweets": 100,
        }
        store.start_run(keywords=["term"], params=thresholds, run_id="run-1")

        result = store.save_user_deep_dive(
            run_id="run-1",
            username="ExampleUser",
            trigger_evidence=evidence_docs(10, 10),
            profile_evidence=evidence_docs(99, 20, offset=100),
            keywords=["term"],
            thresholds=thresholds,
        )

        self.assertEqual(result["status"], STATUS_INSUFFICIENT_DATA)
        self.assertEqual(result["score"]["evaluated_count"], 99)


if __name__ == "__main__":
    unittest.main()
