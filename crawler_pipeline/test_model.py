import asyncio
from twitter_crawler import get_local_classifier
# הערה: אם הקובץ הנוכחי שלך נקרא twitter_crawler.py והוא באותה תיקייה, 
# השתמשי בשורה הזו במקום: מהשורה הקודמת:
# from twitter_crawler import get_local_classifier

def test_single_user_model():
    print("⏳ טוען את המודל לזיכרון (זה עשוי לקחת כמה שניות)...")
    classifier = get_local_classifier()
    print("✅ המודל נטען בהצלחה!")
    print(f"💻 המודל רץ כעת על חומרה מסוג: {classifier.device}\n")

    # רשימת משפטים לבדיקה (את יכולה לשנות אותם למה שבא לך)
    test_tweets = [
        "I love coding in Python and analyzing data!",
        "This is an official statement from the group calling for jihad and resistance.",
        "Just having some coffee and watching the rain outside."
    ]

    print("🔮 מריץ חיזוי על הציוצים...")
    # הרצת הפונקציה predict שניתחנו
    results = classifier.predict(test_tweets)

    # הדפסת התוצאות בצורה קריאה ומסודרת
    for i, res in enumerate(results, 1):
        print("-" * 50)
        print(f"ציוץ מספר {i}: \"{res.tweet}\"")
        print(f"🏷️  לייבל שנבחר: {res.label}")
        print(f"🚨 האם סומן כקיצוני (Flagged): {res.flagged}")
        print(f"🎯 רמת ביטחון (Confidence): {res.confidence * 100:.2f}%")
        print(f"📊 פירוט ההסתברויות המלא: {res.probabilities}")
    print("-" * 50)

if __name__ == "__main__":
    test_single_user_model()