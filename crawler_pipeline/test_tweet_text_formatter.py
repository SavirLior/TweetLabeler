import unittest

try:
    from .tweet_text_formatter import (
        FILTER_ARABIC,
        FILTER_SHORT_TEXT,
        FORMAT_VERSION,
        format_tweet_text,
    )
except ImportError:
    from tweet_text_formatter import (
        FILTER_ARABIC,
        FILTER_SHORT_TEXT,
        FORMAT_VERSION,
        format_tweet_text,
    )


class TweetTextFormatterTests(unittest.TestCase):
    def test_regular_text_removes_url_emoji_and_non_ascii(self):
        result = format_tweet_text(
            {
                "lang": "en",
                "fullText": "Hello ummah 😊 visit https://example.com שלום",
            }
        )

        self.assertIsNotNone(result.formatted)
        self.assertEqual(result.formatted.text, "Hello ummah  visit")
        self.assertEqual(result.formatted.format_version, FORMAT_VERSION)
        self.assertFalse(result.formatted.is_retweet)
        self.assertFalse(result.formatted.is_quote)

    def test_short_text_is_filtered_after_cleaning(self):
        result = format_tweet_text({"lang": "en", "fullText": "abc"})

        self.assertIsNone(result.formatted)
        self.assertEqual(result.filter_reason, FILTER_SHORT_TEXT)

    def test_retweet_uses_retweet_object_text(self):
        result = format_tweet_text(
            {
                "lang": "en",
                "fullText": "RT shell text should not be used",
                "retweet": {
                    "lang": "en",
                    "fullText": "Original retweeted content",
                },
            }
        )

        self.assertIsNotNone(result.formatted)
        self.assertEqual(result.formatted.text, '"Original retweeted content"')
        self.assertTrue(result.formatted.is_retweet)
        self.assertFalse(result.formatted.is_quote)
        self.assertEqual(result.formatted.source_text_kind, "retweet")

    def test_quote_uses_legacy_format(self):
        result = format_tweet_text(
            {
                "lang": "en",
                "fullText": "User response",
                "quote": {
                    "lang": "en",
                    "fullText": "Quoted content",
                },
            }
        )

        self.assertIsNotNone(result.formatted)
        self.assertEqual(
            result.formatted.text,
            '""Quoted content"\n"\n--------------\n\nUser response',
        )
        self.assertTrue(result.formatted.is_quote)
        self.assertEqual(result.formatted.source_text_kind, "quote")

    def test_arabic_main_retweet_or_quote_is_filtered(self):
        arabic_main = format_tweet_text({"lang": "ar", "fullText": "hello"})
        arabic_retweet = format_tweet_text(
            {
                "lang": "en",
                "fullText": "hello",
                "retweet": {"lang": "ar", "fullText": "retweeted"},
            }
        )
        arabic_quote = format_tweet_text(
            {
                "lang": "en",
                "fullText": "hello",
                "quote": {"lang": "ar", "fullText": "quoted"},
            }
        )

        self.assertEqual(arabic_main.filter_reason, FILTER_ARABIC)
        self.assertEqual(arabic_retweet.filter_reason, FILTER_ARABIC)
        self.assertEqual(arabic_quote.filter_reason, FILTER_ARABIC)


if __name__ == "__main__":
    unittest.main()
