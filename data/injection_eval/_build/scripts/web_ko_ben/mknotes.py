import json, sys, re
base = sys.argv[1]
AD = ("AgentDojo plain-text get_webpage output translated into natural Korean; "
      "names/brands kept in Latin script; numbers, percentages and email addresses kept verbatim; trailing whitespace preserved.")
HTML = ("BrowseSafe raw HTML: every tag, attribute name, URL, email, class/id, CSS and the overall markup kept byte-identical "
        "(<html lang=\"en\"> where present left unchanged); translated only human-readable text: text nodes, "
        "title/placeholder/aria-label values, readable text inside HTML-escaped markup (&lt;...&gt; tags kept identical), "
        "and natural-language prose inside HTML/CSS comments (matches the KO injection half, whose comment payloads are Korean). "
        "Recurring boilerplate lines use exactly the renderings from the KO injection half's glossary. Brand/site names in Latin script. "
        "Tag sequence verified identical to the source.")
extra = {
 'web-ben-01': "News register (-다 style); '100,000' kept as digits; 'MarketWatch', 'Market Wrap' kept.",
 'web-ben-02': "Same sentence rendering as the base text of web-inj-01-ko.",
 'web-ben-03': "Same sentence rendering as the base text of web-inj-02-ko.",
 'web-ben-04': "Same sentence rendering as the base text of web-inj-03-ko / web-inj-05-ko.",
 'web-ben-05': "Stray '. .' (empty default injection slot in the source) preserved; 'Zurich Restaurant' kept in Latin script.",
 'web-ben-06': "Video title translated, channel name 'Sambucha' kept; timestamp '2025-11-09' and server id kept.",
 'web-ben-09': "Brand labels 'Facebook', 'Messenger' kept; truncated escaped fragment '&lt;span class=\"nav-link-item\" style' kept as-is.",
 'web-ben-10': "Timestamp 'Mon-Fri 9AM-5PM EST' kept verbatim (as the injection half keeps timestamps); 'Gmail' kept.",
 'web-ben-13': "Course name 'AP Research' kept.",
 'web-ben-14': "Scraped TradingView UI with run-together labels: labels translated and kept run-together; literal '\n' escapes, prices, tickers, timestamps ('09:50:09 UTC+5:30'), OHLC letters, timeframe codes, indicator names and their parameter lists ('ICT Concepts \\[LuxAlgo\\] (...)', 'AlgoAlpha - Breakout Channels (...)') kept verbatim.",
 'web-ben-19': "Brand label 'X' kept.",
 'web-ben-23': "Title dates 'Sep 30 - Oct 6, 2025' kept verbatim, only 'Week of' translated.",
 'web-ben-25': "Text node with CSS declarations: CSS kept byte-identical, only the prose in the /* */ comment translated.",
 'web-ben-27': "Timestamp '10/7/2025, 9:27:43 PM' kept verbatim.",
 'web-ben-30': "Text node with CSS declarations: CSS kept byte-identical, only the prose in the /* */ comment translated.",
}
notes = {}
for i in range(1, 31):
    rid = f'web-ben-{i:02d}'
    notes[rid] = ((AD if i <= 5 else HTML) + (' ' + extra[rid] if rid in extra else '')).strip()
json.dump(notes, open(base + '/notes.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
print(notes['web-ben-14'])
