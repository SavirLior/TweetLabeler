import React from "react";

interface TweetTextProps {
  text: string;
  className?: string;
}

const tweetTextStyle: React.CSSProperties = {
  textAlign: "start",
  unicodeBidi: "plaintext",
};

export const TweetText: React.FC<TweetTextProps> = ({ text, className = "" }) => (
  <p
    dir="auto"
    title={text}
    className={className}
    style={tweetTextStyle}
  >
    {text}
  </p>
);
