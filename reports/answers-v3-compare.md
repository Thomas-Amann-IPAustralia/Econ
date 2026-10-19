# answer-v1 and answer-v3, side by side (D-024)

Six questions, each answered once under each prompt: the same pipeline as the service (plan-v2, the relevance
filter, gpt-6.1-sol at medium effort, the check, streaming on), run locally on 2026-10-19. This container had no
embedding model, so search ran on keywords alone; both prompts saw the same kind of evidence. The sixth question
is a follow-up to the fourth, with that prompt's own earlier answer as the conversation. Every event is in
`eval/runs/answers/answers-v3-compare.jsonl`. Spend: US$0.38 (OpenAI, in the ledger).

## Timings

| | answer-v1 | answer-v3 |
|---|---|---|
| Passed the check first time | 6 of 6 | 6 of 6 |
| First words on screen (median) | 16.9 s | 18.7 s |
| Whole answer, checked (median) | 41.1 s | 44.5 s |
| Prose length (median characters) | 1796 | 2326 |
| Claims (median) | 6 | 8 |
| Cost a question (median) | US$0.033 | US$0.031 |

| Question | v1 first words / total | v3 first words / total |
|---|---|---|
| What statistical methods does the Office of the Chief Economist use to establish causality? | 18.4 / 47.0 s | 19.4 / 52.7 s |
| Do small businesses that own trade marks grow faster? | 15.4 / 21.7 s | 17.9 / 30.1 s |
| What is patent pendency and why does it matter? | 13.5 / 34.0 s | 13.7 / 37.2 s |
| How have patent applications in Australia changed over the last decade? | 27.5 / 48.6 s | 17.4 / 45.7 s |
| What did the research find about the gender gap in IP? | 14.4 / 35.3 s | 21.1 / 43.5 s |
| Why did that happen? Explain it simply. | 26.1 / 55.2 s | 23.3 / 45.5 s |

## The answers

### What statistical methods does the Office of the Chief Economist use to establish causality?

**answer-v1** (complete, 7 claims)

The Office uses several methods to strengthen causal inference, but **does not treat all estimated relationships as proof of causality**. The 2026 report explicitly describes its results as dynamic associations, while the 2021 exporter study acknowledges possible omitted-variable bias and reverse causality.[1]

The methods in the supplied publications are:

- **Difference-in-differences (2024):** The computer-implemented inventions study compares changes in filing propensity before and after changes in legal standards for affected applications relative to non-CII applications. This explicitly aims to identify causal effects. However, it cannot disentangle the separate effects of the *Alice* and *Research Affiliates* decisions.[2]
- **Event studies with comparable firms (2026):** Firms are compared before and after their first IP grant, and against similar firms that have not yet received—or never receive—the right. Comparison firms are similar in age, size, R&D intensity, financial performance and leverage. This helps distinguish pre-existing trends from subsequent shifts, but does not establish definitive causality.[3]
- **Dynamic panel models using generalised method of moments—GMM (2020):** These address endogeneity and omitted explanatory variables. The competition analysis treats lagged outcomes and IP measures as endogenous. Model checks include comparison with ordinary least squares and fixed-effects estimates, plus Hansen and Arellano–Bond tests.[4]
- **Fixed-effects models exploiting within-firm variation (2021):** The exporter study compares the same firm selling the same product across markets facing different shocks. Firm-product-year and product-market fixed effects control for systematic differences, although endogeneity may remain.[5]
- **Robustness and timing checks (2021):** The exporter study varies specifications, measures and samples; examines rejected or cancelled trade mark applications; and uses depreciated trade mark stocks and two-year lags to test whether anticipatory filing could explain the results.[6]
- **Within-patent-family comparisons (2024):** Comparing equivalent applications across three patent offices helps distinguish differences in legal standards and practices from underlying invention, application or applicant characteristics.[7]

**answer-v3** (complete, 9 claims)

The Office uses **comparisons over time and between groups, statistical models, and robustness checks** to investigate causality—not just simple correlations.[1][3][4] But these methods do not automatically prove cause and effect: its 2026 productivity analysis explicitly describes its findings as associations, not definitive causal effects.[2]

### 1. Difference-in-differences: compare changes against a comparison group
This method asks whether an outcome changed more for an affected group than for a comparison group after an event. The comparison helps distinguish the event’s possible effect from changes that might have happened anyway.

In its 2024 research on computer-implemented inventions, the Office used **difference-in-differences** to compare filing behaviour before and after changes in legal standards, relative to applications for other inventions.[1] One limitation was that it could not separate the effects of the two legal decisions examined—*Alice* and *Research Affiliates*.[5]

### 2. Event studies: track the path before and after
An event study looks at how outcomes evolve around an event, rather than simply comparing one “before” and one “after” observation.

The 2026 analysis compared firms before and after their first intellectual property (IP) grant with similar firms that had not yet received—or would never receive—the same right; comparison firms were similar in age, size, research and development intensity, financial performance and leverage.[2] This helps distinguish existing trends from changes emerging after IP engagement, but firms choose whether to seek rights, so the analysis does not establish definitive causality.[2]

### 3. Panel-data models: account for persistent differences and past outcomes
Panel data follow the same firms or industries over time. **Fixed effects** help account for persistent differences between them that could otherwise distort a comparison.

For example, the 2021 trade mark and export study compared the same firm selling the same product in different country markets, using fixed effects to account for firm-product-year and product-market differences.[6]

The 2020 profitability research used **System Generalised Method of Moments (GMM)**, a dynamic panel method, to improve control for endogeneity, omitted explanatory variables and relationships among explanatory variables.[3] Its industry competition analysis used both Difference GMM and System GMM, alongside other models to check robustness.[7] Here, “endogeneity” means that the factors being studied may be entangled—for example, an apparent effect could reflect reverse causality or an unmeasured influence.

### 4. Robustness checks: test competing explanations
In the export study, the Office changed model specifications, measures and samples, and tested earlier trade mark activity—including two-year lags—to investigate whether anticipated export expansion might explain the relationship.[4] Similar results with those alternative measures reduced concerns about reverse causality, rather than eliminating them.[8]

**The practical takeaway:** look at the research design and its stated limitations, not just whether a result is statistically significant. The export study, for example, acknowledged that unmeasured characteristics of firms’ regional divisions could still affect its estimates despite extensive controls.[9]

*Follow-ups offered:* Can you explain difference-in-differences with a simple example? · What did the 2026 productivity study find, and how confident should we be? · How does the Office check for reverse causality in trade mark research?

### Do small businesses that own trade marks grow faster?

**answer-v1** (complete, 2 claims)

**Yes—trade mark activity is a predictor of subsequent growth among Australian small and medium enterprises (SMEs), but that does not by itself establish that trade marks cause faster growth.**[1]

Research summarised in a 2025 IP Australia paper found that SMEs filing for a trade mark were **16% more likely to achieve positive employment growth over three consecutive years** than peers with no recent filings.[2] That means a higher likelihood of growth—not a 16% faster growth rate. The finding concerns SMEs that **file** for trade marks, rather than all small businesses that own them.[2]

**answer-v3** (complete, 4 claims)

**Yes—the evidence points that way for employment growth, although the clearest small-business finding concerns filing for a trade mark, rather than simply owning one.** Australian small and medium-sized enterprises (SMEs) that file for a trade mark are **16 per cent more likely to achieve positive employment growth over three consecutive years** than peers with no recent filings.[1] That means a higher likelihood of growth—not employment growing 16 per cent faster.

The underlying research covered around **600,000 Australian SMEs active between 2002 and 2017**.[2] A related descriptive comparison matched first-time trade mark filers with non-filers of similar age, size and industry: employment was flat for both groups before filing, but afterwards filers showed continuing employment growth, while non-filers grew much less.[3]

So, trade mark filing looks useful as a signal of future employment growth.[4] But these comparisons alone do not establish that the trade mark caused the growth.

*Follow-ups offered:* What does the evidence say about trade marks and business income? · How do the growth findings compare with patents and design rights?

### What is patent pendency and why does it matter?

**answer-v1** (complete, 6 claims)

**Patent pendency is the time a patent application spends in the patent system before a final outcome**, such as grant, lapse or refusal—not simply the time spent being examined. Applicants generally think of it as the time to grant; IP Australia also considers the time until an application leaves its inventory.[1]

**How it is measured matters:**
- **Exit pendency** groups applications by when they reach a final outcome.
- **Entry pendency** groups applications by when they were filed and follows their time to a final outcome.[2]

Pendency reflects both office processing and applicant choices. Australia operates a deferred examination system: applicants must request examination, and some applicants deliberately take longer to proceed.[3] For a narrower timing measure, the *Australian IP Report 2025* reported a median **1.3 years from requesting examination to acceptance for grant**, using 2020 data—the latest complete data cited. This is not the full filing-to-grant period.[4]

**Why it matters:**
- **Commercialisation and further innovation:** faster examination is associated with stronger post-grant outcomes overall, but the relationship differs by applicant. For large businesses, faster office processing is linked to more commercialisation and follow-on innovation; small innovators can benefit from delays. Faster is therefore not necessarily better for every applicant.[5]
- **Competition:** grant delays create uncertainty about whether a patent will be granted and what it will cover. That uncertainty can discourage rivals’ investment, R&D and market entry. The 2025 report found delays tend to slow and narrow rivals’ follow-on innovation, although an equivalent overseas grant can partly reduce the uncertainty.[6]

**answer-v3** (complete, 8 claims)

**Patent pendency is the time a patent application spends in the system before a final outcome**—such as grant, lapse or refusal.[1] It matters because processing delays are a central cost of patent backlogs, but a longer wait is not always bad for the applicant: the findings suggest its effects differ between small and large businesses.[3][5][6]

### How is it measured?
The 2014 report distinguishes two ways of measuring pendency:[1]
- **Entry pendency:** group applications filed in the same month and measure how long they take to reach a final outcome.[1]
- **Exit pendency:** group applications reaching a final outcome in the same month and measure how long they spent in the system.[1]

It is worth checking the definition in any particular analysis: the 2024 computer-implemented inventions study, for example, measures pendency as the number of years between filing year and grant year.[2]

### Why does it matter?
**It helps us understand delays—but not all elapsed time is office processing time.** The 2014 report explains that some pendency reflects applicant behaviour, with deferred examination allowing applicants to wait before progressing their applications.[3]

**Timing is linked to commercial outcomes.** The Australian IP Report 2025 reports that applicants who speed up examination tend to be more likely to renew, commercialise and build on their patents.[4] But the picture differs by business size:
- **For large businesses,** faster office processing is linked to more commercialisation and follow-on innovation.[5]
- **For small businesses,** the 2024 report found that longer filing-to-grant periods tended to increase the likelihood of eventual commercialisation, while applicant-side delays were linked to more follow-on innovation within the firm.[6]

These are reported relationships, not a guarantee that changing the timing will produce the same result for every applicant.

**It also affects how we interpret statistics.** Recent filing groups may look faster simply because many of their slower applications are still awaiting an outcome—a problem called *censoring*.[7] In everyday terms, judging a queue only by those who have already finished can miss those still waiting.

The practical takeaway from the 2025 report is a balance: faster processing is likely to deliver economic benefits, provided applicants retain sufficient flexibility to influence their application timeframes.[8]

*Follow-ups offered:* Why might delaying examination help a small business? · How has patent pendency changed over time in Australia? · How can we separate applicant delays from office delays?

### How have patent applications in Australia changed over the last decade?

**answer-v1** (complete, 6 claims)

**Patent applications have grown modestly overall, but not steadily.** The latest supplied figures are for 2024: standard patent applications totalled 30,478, calculated by adding resident and non-resident filings. That was about 6.5 per cent above the 28,605 applications recorded in 2015.[1]

- **Growth has been interrupted by declines.** Standard applications fell by 0.7 per cent to 29,758 in 2019, then to 29,293 in 2020—a decrease reported as 2 per cent.[2]
- **Overseas applicants still dominate.** Non-residents accounted for 91.5 per cent of standard applications in 2024, and reduced non-resident filings entirely explained that year's overall decline. Australian resident applications, by contrast, rose by 0.9 per cent to 2,578.[3]
- **SMEs have become more prominent among domestic applicants.** Their share of resident standard filings increased from 57.9 per cent in 2014 to 62.9 per cent in 2023.[4] In 2024, filings from Australian SMEs rose by 1.9 per cent and those from individuals by 3.9 per cent; together they accounted for 87.2 per cent of resident filings. Large-firm filings fell by 6.9 per cent.[5]
- **Provisional applications have recently reversed their longer-term decline.** They reached 4,344 in 2024, up 2.4 per cent—the second consecutive annual increase after a negative trend over the preceding decade. The likelihood of converting provisional applications into standard complete applications has also increased over the past decade.[6]

**answer-v3** (complete, 12 claims)

**Patent applications in Australia are modestly higher than a decade ago, but growth has been uneven.** Standard patent applications rose from 28,605 in 2015 to 30,348 in 2025; the latest report describes recent trends as normalisation after a post-pandemic peak, rather than contraction.[1][2]

The main changes are:

- **Overall filings have eased recently.** Applications fell from 31,530 in 2023 to 30,487 in 2024 and 30,348 in 2025—a decline of 3.8 per cent over those two years.[2]
- **Australian resident applications have strengthened.** Residents filed 2,810 standard applications in 2025, up 9.0 per cent from 2024, bringing their share to 9.3 per cent—the highest since 2021.[3] Small and medium-sized enterprises (SMEs) have become more prominent: their share of resident filings rose from 57.9 per cent in 2014 to 62.9 per cent in 2023.[4]
- **Overseas applicants still dominate, but their mix has changed.** Non-residents accounted for 90.7 per cent of standard filings in 2025.[5] The United States remained the leading overseas origin in 2024, but its filings fell for a second consecutive year, while China-origin filings reached a record high.[6] China’s longer-term growth has nevertheless slowed: filings grew by an annual average of 7 per cent over the five years to 2024, compared with 30 per cent over the five years to 2019.[7]
- **Health technologies are a major part of the picture.** The 2026 report identifies a gradual increase in the life sciences share over the preceding decade; pharmaceuticals, medical technology and biotechnology together accounted for 33.3 per cent of standard filings in 2025.[8]

**Provisional applications have followed a different path.** These establish an early priority date but provide no enforceable protection.[9] The 2024 report described a decade-long decline relative to standard filings, driven mainly by fewer filings from individuals; the latest report, however, says provisional filings expanded sharply in 2025.[10][11]

The important caution is that **patenting is not a measure of innovation across all Australian businesses**: resident patenting reflects a relatively small group engaged in research and development-intensive, technologically specialised innovation.[12]

*Follow-ups offered:* How has the role of SMEs in patenting changed? · Which technology fields are growing or declining? · What is the difference between a patent application and a patent grant?

### What did the research find about the gender gap in IP?

**answer-v1** (complete, 6 claims)

The research found a **persistent gender gap in patenting, but no systematic productivity difference between women and men** in creative and innovative work.[1]

- **Women remained under-represented.** The 2023 report found that women accounted for about 15 per cent of unique inventors on Australian PCT applications—2 percentage points below the international average.[2]
- **Participation was increasing, without clear growth in the women inventor pool.** In the three years to 2022, the share of Australian PCT applications naming at least one woman rose by 3 percentage points to 26 per cent. However, women’s share of unique inventors stayed at 14.6 per cent in both 2021 and 2022. Growth appeared concentrated in mixed-gender teams; another possible explanation was that existing women inventors were patenting more intensively.[3]
- **The gap varied substantially by technology.** In 2022, women were named on 61 per cent of Australian PCT applications in biotechnology and 59 per cent in both organic fine chemistry and pharmaceuticals. These are shares of applications naming women, not women’s shares of all inventors.[4]
- **Potential barriers included recognition and funding.** The report identified the nature of women’s research, under-crediting of women’s scientific contributions and research-funding disparities as possible contributors—not established explanations for the entire gap.[5]
- **Women’s participation was associated with stronger innovation outcomes in some businesses.** Among R&D businesses, greater women’s representation in leadership was associated with more efficient conversion of R&D expenditure into patents, despite lower R&D intensity. Women’s participation in start-up management was also associated with greater overall IP holdings. These were reported as associations rather than causal findings.[6]

**answer-v3** (partial, 9 claims)

The main finding was that **women remained under-represented in patenting, even though their participation was increasing**.[1] The research did not find systematic productivity differences between women and men in creative and innovative work.[2]

### How large was the gap?
The 2023 Australian IP Report found that women accounted for about **15 per cent of unique inventors** on Australian applications through the Patent Cooperation Treaty (PCT) international filing route—2 percentage points below the international average.[3]

There was progress, but an important distinction between **more applications involving women** and **more women entering the inventor pool**:
- In the three years to 2022, the share of Australian PCT applications naming at least one woman rose by 3 percentage points to **26 per cent**.[4]
- Yet women’s share of individual Australian inventors was **14.6 per cent in 2022, unchanged from 2021**.[5]

The report suggested that growth was occurring in mixed-gender teams, but also offered another possible explanation: existing women inventors might be patenting more often, without substantial growth in the number of women inventors.[6]

### What might explain it?
The gap varied considerably by technology: in 2022, women were named on 61 per cent of PCT applications in biotechnology and 59 per cent in both pharmaceuticals and organic fine chemistry.[7] The report identified possible contributing factors including the nature of women’s research, under-crediting of their contributions and unequal research funding—not a single established cause.[8]

There was also a related business-level finding: among firms with a science, technology, engineering and mathematics (STEM) workforce, women’s representation in leadership was associated with lower research intensity but greater efficiency in converting research and development investment into intellectual property.[9] That is an association, not proof that leadership composition caused those outcomes.

These passages mainly address patents and innovation; they do not establish the size of the gender gap across every type of intellectual property.

*Not covered:* The passages do not provide gender-gap estimates for trade marks, designs or plant breeder’s rights.; The passages identify possible contributors to the patenting gap but do not establish their individual causal effects.

*Follow-ups offered:* Why does the distinction between applications and individual inventors matter? · What does the research say about funding barriers for women inventors? · How is diversity in business leadership linked to innovation?

### Why did that happen? Explain it simply.

(A follow-up to: "How have patent applications in Australia changed over the last decade?")

**answer-v1** (complete, 7 claims)

**The changes reflect overseas filing decisions, temporary policy effects and, recently, more people entering through provisional applications—not steady growth every year.** Standard applications rose from 28,605 in 2015 to 30,348 in 2025: about **6.1 per cent growth over the decade**, calculated from the reported totals.[1]

- **Overseas applicants largely determine the overall result.** In 2025, non-residents accounted for 90.7 per cent of standard applications. Their filings fell by 1.3 per cent, outweighing a 9.0 per cent rise in Australian resident filings. Total applications consequently slipped by 0.5 per cent.[2]

- **The pandemic-era strength has eased.** The 2023 report linked strong applications in 2021–22 to resilient global innovation investment, demand for innovations such as healthcare and ecommerce, and fiscal support. The latest report describes subsequent declines as a return towards normal levels after the post-pandemic peak, rather than an ongoing contraction.[3]

- **Policy changes shifted some applications between years.** The innovation patent phase-out likely encouraged applicants to bring standard applications forward into 2021, preserving the option to convert or divide them into innovation patents. The subsequent fall in resident applications in 2022 was therefore partly a correction—not simply a drop in inventive activity.[4]

- **Provisional filings have rebounded sharply.** Earlier declines were mostly driven by fewer individual applicants, while filings by large organisations and SMEs stayed relatively stable. In 2025, provisional filings reached 6,867, up 58.1 per cent. Provisionals let applicants secure an early priority date while deferring the cost and commitment of a complete application.[5]

- **Digital tools may be making that first step easier—but this is not proven.** The 2026 report suggests AI-assisted drafting and searching may reduce entry costs. Consistent with that explanation, new filers represented 63 per cent of provisional applicants in 2025, and applicants without a patent attorney represented 52 per cent. These patterns support a possible explanation, not proof that AI caused the increase.[6]

**The key caution:** Australian resident patenting reflects a relatively small group of R&D-intensive, technologically specialised firms, so changes in patent applications should not be read as a broad measure of business activity.[7]

**answer-v3** (partial, 6 claims)

**The reports point to several reasons, rather than one:** the pandemic changed demand for inventions, digital patenting surged and then eased, legal uncertainty affected some software-related filings, and smaller businesses became more important in domestic patenting.[1][2][3][4]

Here’s the simple version:

- **The pandemic boosted health-related patenting.** Pharmaceutical applications were already growing from 2016, but growth accelerated during the first two years of COVID-19 and continued in 2022. Medical technology and biotechnology also increased their shares of filings.[1]
- **Digital technologies had a surge, followed by a cooling-off period.** Computer technology and digital communication expanded rapidly between 2018 and 2021, alongside pandemic-era digital adoption and the scaling of cloud and artificial intelligence systems. Computer technology filings then fell by 10.1 per cent in 2025; the latest report interprets the easing as a return from unusually high levels, rather than a structural retreat.[2]
- **Uncertainty about what can be patented likely discouraged some applications.** The 2026 report says uncertainty over patent eligibility for software and computer-implemented inventions is likely to have dampened filings in some fields.[3] Put simply, uncertainty about whether an invention qualifies can affect the decision to apply.
- **The businesses doing the patenting have changed.** Research published in 2024 identifies a shift in domestic patenting from large firms towards small and medium-sized enterprises (SMEs), alongside a retreat in large-firm research and development spending. SMEs’ share of national research and development spending rose from around 30 per cent in 2007 to 55 per cent in 2022.[4]

**Taken together, these changes help explain why the headline total hides quite different stories.** Standard applications edged down from 31,530 in 2023 to 30,348 in 2025, which the latest report describes as post-pandemic normalisation rather than contraction.[5]

One caution: **fewer applications do not automatically mean fewer inventions.** The research on computer-implemented inventions distinguishes between applicants having fewer inventions to patent, choosing not to seek protection, and filing inventions in different patent categories.[6] The supplied evidence does not quantify how much each factor explains the overall decade-long change.

*Not covered:* The passages do not quantify how much each factor contributed to the overall change in applications across the decade, or provide a complete explanation of changes in resident and overseas filings.

*Follow-ups offered:* Why have SMEs become more important in domestic patenting? · How do researchers separate changes in innovation from changes in filing strategy? · Have provisional patent applications followed the same pattern?
