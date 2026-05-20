import React from "react";

interface TweetTextProps {
  text: string;
  className?: string;
}

const rtlCharacterPattern = /[\u0590-\u08ff]/g;
const ltrCharacterPattern = /[A-Za-z]/g;

const getTweetDirection = (text: string): "ltr" | "rtl" => {
  const rtlCount = text.match(rtlCharacterPattern)?.length || 0;
  const ltrCount = text.match(ltrCharacterPattern)?.length || 0;

  return ltrCount >= rtlCount ? "ltr" : "rtl";
};

export const TweetText: React.FC<TweetTextProps> = ({ text, className = "" }) => {
  const direction = getTweetDirection(text);

  return (
    <p
      dir={direction}
      title={text}
      className={`${className} ${direction === "ltr" ? "text-left" : "text-right"}`}
      style={{ unicodeBidi: "isolate" }}
    >
      {text}
    </p>
  );
};
