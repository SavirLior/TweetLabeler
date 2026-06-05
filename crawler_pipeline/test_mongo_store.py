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
        calculate_classification_score,
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
        calculate_classification_score,
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
        return all(doc.get(key) == value for key, value in filter_doc.items())

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
    def test_classification_threshold_uses_ten_percent_ratio_and_minimum_profile_size(self):
        ninety_nine_with_many_positive = calculate_classification_score(
            evidence_docs(99, 20),
            positive_ratio_threshold=0.10,
            min_positive_tweets=0,
            min_evaluated_tweets=100,
        )
        self.assertEqual(ninety_nine_with_many_positive["status"], STATUS_INSUFFICIENT_DATA)

        nine_of_one_hundred = calculate_classification_score(
            evidence_docs(100, 9),
            positive_ratio_threshold=0.10,
            min_positive_tweets=0,
            min_evaluated_tweets=100,
        )
        self.assertEqual(nine_of_one_hundred["status"], STATUS_NOT_SALAFI_JIHADI)

        ten_of_one_hundred = calculate_classification_score(
            evidence_docs(100, 10),
            positive_ratio_threshold=0.10,
            min_positive_tweets=0,
            min_evaluated_tweets=100,
        )
        self.assertEqual(ten_of_one_hundred["status"], STATUS_SALAFI_JIHADI)

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

    def test_jihadi_classification_takes_priority_over_taklidi(self):
        score = calculate_classification_score(
            evidence_docs(100, 30, taklidi=40),
            positive_ratio_threshold=0.10,
            min_positive_tweets=1,
            min_evaluated_tweets=100,
        )

        self.assertEqual(score["status"], STATUS_SALAFI_JIHADI)

    def test_save_user_deep_dive_writes_only_crawler_collections_and_is_idempotent(self):
        fake_db = FakeDb()
        store = CrawlerMongoStore(db=fake_db)
        thresholds = {
            "positive_ratio_threshold": 0.12,
            "min_positive_tweets": 8,
            "min_profile_evaluated_tweets": 4,
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
        )
        store.save_user_deep_dive(
            run_id="run-1",
            username="@ExampleUser",
            trigger_evidence=trigger,
            profile_evidence=profile,
            keywords=["term"],
            thresholds=thresholds,
        )

        self.assertEqual(
            set(fake_db.collections),
            {RUNS_COLLECTION, USERS_COLLECTION, USER_RUNS_COLLECTION, EVIDENCE_COLLECTION},
        )
        self.assertEqual(len(fake_db[USERS_COLLECTION].docs), 1)
        self.assertEqual(len(fake_db[USER_RUNS_COLLECTION].docs), 1)
        self.assertEqual(len(fake_db[EVIDENCE_COLLECTION].docs), 5)
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
