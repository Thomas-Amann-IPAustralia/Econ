# answer-v4 and answer-v5, side by side (D-026)

answer-v5 is answer-v4 with one change: the model cites numbered sentences (`[3.2]`) and writes no claims or
quotes; code builds each claim's quotes from the cited sentences. Six questions, each answered once under
each prompt, the same pipeline as the service (plan-v2, the relevance filter, gpt-6.1-sol at medium effort,
the check, streaming on), run locally on 2026-10-19 with keyword search only (no embedding model in this
container). The sixth question follows up the fourth. Events: `eval/runs/answers/answers-v5-compare.jsonl`.
Spend: US$0.42 (OpenAI, in the ledger).

Note: in this run the claim labels that code wrote for answer-v5 (shown in the trail's claim list) could carry
an earlier claim's ids, such as "[1.4][3.2] It matters…"; fixed after the run (`cite._claim_text`, with a
test). The prose, the quotes and the check results are unaffected.

## Timings and size

| Median over 6 questions | answer-v4 | answer-v5 |
|---|---|---|
| Passed the check first time | 5 of 6 | 6 of 6 |
| Whole answer, checked | 50.2 s | 31.6 s |
| The answer model's call | 38.1 s | 21.4 s |
| First words on screen | 18.5 s | 16.4 s |
| Output tokens (of which reasoning) | 2134 (262) | 1026 (151) |
| Input tokens | 7540 | 8548 |
| Prose, characters | 3440 | 3624 |
| Claims / quoted sentences or quotes | 10.5 / 15 | 15.5 / 31 |
| Cost a question | US$0.040 | US$0.027 |

| Question | v4 whole answer | v5 whole answer |
|---|---|---|
| What statistical methods does the Office of the Chief Economist use to establish causality? | 70.7 s | 40.5 s |
| Do small businesses that own trade marks grow faster? | 61.8 s | 25.4 s |
| What is patent pendency and why does it matter? | 41.6 s | 27.6 s |
| How have patent applications in Australia changed over the last decade? | 52.6 s | 43.3 s |
| What did the research find about the gender gap in IP? | 47.8 s | 32.2 s |
| Why did that happen? Explain it simply. | 41.1 s | 31.0 s |

## The answers

### What statistical methods does the Office of the Chief Economist use to establish causality?

**answer-v4** (complete, 13 claims)

The Office of the Chief Economist uses several statistical approaches to investigate cause and effect—but it does **not** treat every estimated relationship as proof of causality.[1] The important distinction is between a method designed to identify a causal effect and methods that reduce alternative explanations without ruling them out completely.

## 1. Difference-in-differences: comparing changes around a legal reform

The 2024 study of computer-implemented inventions uses **difference-in-differences** to investigate changes in patenting following the 2014 *Research Affiliates* and *Alice* court rulings.[2] It compares filing behaviour before and after the changes in legal standards for computer-implemented inventions, relative to other inventions.[2]

In everyday terms, this asks: did the affected group change more than a comparison group? The comparison helps account for changes that might have happened anyway. A causal interpretation depends on whether the comparison provides a credible picture of what would have happened without the legal change.

There is an important limit: the study cannot separate the effects of the two rulings.[3]

## 2. Event studies: tracking firms before and after their first IP grant

The **Australian IP Report 2026** uses an event-study framework, comparing firms before and after their first grant with similar firms that have not yet received—or never receive—the same right.[4] Comparison firms are similar in age, size, research and development intensity, financial performance and leverage.[4]

This design helps distinguish an existing growth trend from a shift emerging after intellectual property (IP) engagement.[5] But the report explicitly describes its results as **dynamic associations, not definitive causal effects**: firms expecting growth may already have stronger incentives to invest in IP.[5]

That is a useful example of the Office being careful about what a sophisticated method can establish.

## 3. Dynamic panel models: accounting for past performance and other influences

The 2020 profitability research uses **System Generalised Method of Moments (GMM)** models, which the study describes as providing greater control over endogeneity and missing explanatory variables than traditional regression approaches.[6]

“Endogeneity” means that the factor being studied is entangled with other influences on the outcome—for example, because causation runs both ways or an important influence is missing from the model.

For its industry competition analysis, the study applies both Difference GMM and System GMM, and checks their results against ordinary least squares and fixed-effects models.[7] That analysis follows 87 industry subdivisions over 15 periods, from 2001–02 to 2015–16.[7]

These are ways to strengthen the analysis and test its stability, rather than a reason to assume causality automatically.

## 4. Like-for-like comparisons and fixed effects

The Office also tries to make comparisons less vulnerable to underlying differences:

- **Within-firm comparisons:** the 2021 trade mark and exporting study uses fixed effects to identify export-diversification responses from the same firm's behaviour in different destination markets.[8] Fixed effects are a way of accounting for characteristics shared within a group, rather than attributing their influence to the variable of interest.
- **Equivalent patent applications:** the 2024 computer-implemented inventions study compares “patent triplets”—applications from the same patent family filed at three offices—and uses regression controls for other influences on grant outcomes.[9] This makes differences in outcomes more plausibly attributable to legal standards and practices, rather than differences between inventions or applicants.[9]

## 5. Robustness checks: testing competing explanations

The exporting study changes model specifications, measurements and samples; examines rejected or cancelled trade mark applications; and tests accumulated trade mark stocks and two-year lags.[10] These checks address the possibility that firms file trade marks because they already anticipate export expansion, rather than trade marks driving the subsequent outcome.[10]

For export diversification, results remained similar using accumulated stocks and two-year lags, reducing—but not eliminating—concerns about reverse causality.[11] The study also acknowledges that unmeasured characteristics of firms' regional divisions could affect its estimates.[12]

**Bottom line:** taken together, these studies show an approach based on stronger comparisons, controls and checks—not a single statistical “causality test”.[2][4][6][10] The Office also identifies limits to attribution: its 2024 *Raising the Bar* analysis notes that anticipation or other factors beginning around 2010 could affect how much of the estimated change is attributable to the reforms.[13]

Sources:

- [1] “In essence, the DID analysis aims to identify the causal effect of the changes in the legal standards” / “Because firms make the decision whether or not to seek IP rights, the results suggest dynamic associations, not definitive causal effects.”
- [2] “In essence, the DID analysis aims to identify the causal effect of the changes in the legal standards by comparing the propensity of CII patent applications to be filed before and after the changes relative to the propensity of non-CII patent applications.” / “The Full Federal Court of Australia's appeal ruling on the Research Affiliates LLC v Commissioner of Patents in Australia on 18 November 2014, and

The US Supreme Court's ruling on Alice Corp v CLS Bank International in the United States on 19 June 2014.”
- [3] “It is not possible in our analysis to disentangle the possible differential effect of "Alice" and "Research Affiliates".”
- [4] “It compares firms before and after they receive their first grant and compares them with peers that have not yet received the same right (or which will never receive a right).” / “The peers used for comparison are similar to the focal firms across a range of key attributes - age, size, R&D intensity, financial performance (Return on Assets) and leverage (total liability relative to total assets).”
- [5] “Because firms make the decision whether or not to seek IP rights, the results suggest dynamic associations, not definitive causal effects. Firms expecting growth may have stronger incentives to invest in IP, as fixed costs can be spread across expanding sales.” / “That said, the study design helps distinguish continuation of earlier trends from shifts that emerge after IP engagement.”
- [6] “we use System GMM models to estimate regressions concerning the determinants of profitability.” / “(i) greater control of endogeneity; (ii) greater control of possible collinearity of the explanatory variables; and (iii) greater effectiveness in controlling the effects caused by the absence of explanatory variables relevant in explaining the dependent variable.”
- [7] “this is a strongly balanced panel dataset with 87 groups of industry subdivisions (N) and 15 time periods (T) from 2001-02 to 2015-16.” / “Both Difference GMM and System GMM are adopted to address the potential econometric issues related to dynamic panel data and to check the results' robustness. Pooled OLS and fixed effects models were also separately applied to set upper and lower bounds to check the results obtained from different GMM estimations”
- [8] “We include in our regressions firm-year and market fixed effects. As a result, we identify responses based on the differential behaviour of the same firm in different destination markets.”
- [9] “"patent triplets," patent applications which belong to the same patent families, where equivalent applications (for the same or similar inventions) are filed in the 3 patent offices.” / “By comparing outcomes within the same patent families, we can more confidently attribute any observed differences in the likelihood of grant across the 3 offices to variations in legal standards and practices across jurisdictions” / “Furthermore, we also estimate econometric models of patent examination outcomes controlling for other possible factors that could lead to different patent examination outcomes across the patent offices.”
- [10] “These tests included using different model specifications, changing the measurement of dependent and independent variables, and varying the estimation sample.” / “First, we examine the elasticity of export outcomes with respect to trade mark applications that are rejected or cancelled” / “The trade mark stock variable captures trade mark activity over an extended period prior to the window of analysis and so estimated effects of this variable are less likely to be influenced by export expansion planned in anticipation of tariff changes or changes in the real exchange rate.” / “In addition, we re-estimate models using 2-year lags to test whether our results hold for filing behaviour less likely to reflect pre-emptive filing behaviour.”
- [11] “results in Model 21 are similar to our baseline analysis using a depreciated trade mark stock variable in place of the measure of annual filing activity.” / “results are similar to the baseline in a model using 2-year lags of all independent variables (Model 22). These findings reduce concerns that our main results are a product of reverse causality”
- [12] “our inability to adequately control for the characteristics of firms' regional divisions could inflate the standard errors for our variables of interest or alter the sign of these variables' coefficients”
- [13] “some of the effects of the RTB reforms could have been anticipated or that there are other factors (which may or may not be related to the RTB reform) which, starting around 2010, led to a decline in the proportion of broader AU patents.” / “if these factors were unrelated to the RTB reforms, then some components of the estimated impacts of RTB may not be attributable to the reforms.”

*Follow-ups offered:* What did the 2026 event study find about productivity? · Can you explain reverse causality using the trade mark study? · What limits the causal interpretation of the patent reform studies?

**answer-v5** (complete, 17 claims)

The Office uses several statistical approaches to get closer to cause and effect: **difference-in-differences, event studies with comparable firms, and models that follow firms or industries over time**. But it distinguishes between estimating a causal impact and identifying an association: its 2026 firm-performance study explicitly says its results are not definitive causal effects. [1]

The central question is: *what would have happened without the policy change or IP engagement?* The methods below construct different ways of making that comparison.

## 1. Difference-in-differences: compare changes, not just outcomes

This method compares the before-and-after change for an affected group with the change for a comparison group. The Office used it in its 2024 study of legal standards for computer-implemented inventions, examining both patent grant probabilities and application probabilities. [2]

Rather than attributing every change after a court ruling to that ruling, the analysis compared changes for computer-implemented inventions with changes for other patent applications. The two relevant court rulings occurred in 2014, so their impacts were investigated together rather than separately. [3]

The Office also used a model equivalent to difference-in-differences to assess the **2013 Raising the Bar reforms**, comparing Australian patent claims with their European and US counterparts before and after the reforms. [4]

**How much confidence does that give us?** The Raising the Bar study says its causal interpretation depends on there being no other relevant policy changes in the jurisdictions being compared. [5] More generally, this kind of comparison is convincing only if the comparison group provides a credible guide to what would otherwise have happened.

That caution matters in practice: the 2024 Australian IP Report estimated that the reforms reduced the likelihood of Australian patents being broader than their international equivalents by **1.0 to 4.0 percentage points**, but warned that narrowing had begun before the reforms. The results nevertheless held when the study focused on a shorter period immediately around the reforms. [6]

## 2. Event studies and comparable firms: track what changes around IP engagement

The **2026 Australian IP Report** compares firms before and after their first IP grant with similar firms that have not yet received the same right, or never receive one. The comparison firms are similar in age, size, research and development intensity, financial performance and leverage. [7]

This design helps distinguish an existing growth trend from a shift that emerges after IP engagement. [8] The Office has also described matching grant recipients with non-participants on observable characteristics—such as size, patent status, industry and location—to reduce the risk of confusing pre-existing differences with the effects of a grant. [9]

**The limitation is selection:** firms choose whether to seek IP rights, and firms already expecting growth may be more inclined to do so. The 2026 report therefore describes its findings as dynamic associations, not definitive causal effects. [10] Matching improves comparability on the characteristics measured; it does not, by itself, rule out differences that were not measured.

## 3. Fixed-effects models: compare like with like over time

In its **2021 trade marks and exporting study**, the Office compared the same firm selling the same product in different country markets, where it faced different shocks. It used fixed effects to account for firm-product-year characteristics and persistent product-market differences. [11]

In everyday terms, fixed effects help remove systematic differences that might otherwise distort a comparison. But they do not remove every possible source of bias: the study acknowledges both missing information and reverse causality—for example, a firm might register trade marks because it anticipates export expansion, rather than trade marks causing that expansion. [12]

## 4. Dynamic panel models and generalised method of moments

The **2020 profitability and competition study** used generalised method of moments (GMM), including System GMM and Difference GMM. These methods were selected to address statistical problems arising when outcomes depend on their own past values and when explanatory factors may themselves be influenced by the outcome. [13]

For profitability, the model includes past profitability because earlier profits can support subsequent investment. System GMM was chosen for data covering many firms over relatively short, uneven periods, and to better account for unobserved differences between firms. [14]

These methods strengthen the analysis, but their statistical properties still depend on assumptions; they are not automatic proof of causality. [15]

## How the Office checks its conclusions

The publications also test whether findings survive alternative specifications. Examples include using trade mark activity measured two years earlier to reduce concerns about reverse causality, comparing different GMM estimators, and checking model diagnostics. [16]

**The bottom line:** the Office builds a causal case through credible comparison groups, timing, controls and robustness checks. The strength of that case varies by study—and the publications explicitly flag where selection, earlier trends or other changes prevent a firm causal conclusion. [17]

Sources:

- [1] “The third empirical analysis of the CII patent applications involves a difference-in-differences (DID) analysis of the impact of variation in the relevant CII patenting legal standards within and across the different patent offices.” / “The analysis uses a modern event study framework.” / “Because firms make the decision whether or not to seek IP rights, the results suggest dynamic associations, not definitive causal effects.” / “Both Difference GMM and System GMM are adopted to address the potential econometric issues related to dynamic panel data and to check the results' robustness.”
- [2] “Due to their occurring in the same year, the impact of the 2 court rulings will be investigated simultaneously using the difference-in-differences (DID) method, comparing the measured change in the outcome variable before and after the court decision of the treated group to that of the control group.” / “Two different outcome variables will be considered: Probability of patent grant and Probability of patent application.”
- [3] “In essence, the DID analysis aims to identify the causal effect of the changes in the legal standards by comparing the propensity of CII patent applications to be filed before and after the changes relative to the propensity of non-CII patent applications.” / “Due to their occurring in the same year, the impact of the 2 court rulings will be investigated simultaneously using the difference-in-differences (DID) method, comparing the measured change in the outcome variable before and after the court decision of the treated group to that of the control group.”
- [4] “where i indexes each pair AU-EP and AU-US patents in the estimating sample, Scopei is the manually assessed or ML classified relative scope based on the first (or all) claims, RTBi is an indicator with a value of 1 if the corresponding Australian patent has an exam request date after the RTB reforms date (16 April 2013) and 0 otherwise, and is a set of explanatory variables including an indicator variable if the patent pair is AU-US, common text similarity measures, and indicator variables for the exam sections.” / “To interpret the key parameter of interest , we note that while the model is a linear probability model estimated using Ordinary Least Squares (OLS), it is functionally equivalent to a Difference-in-Differences model with the first difference represented by the AU-EP and AU-US claim comparisons.”
- [5] “15 This interpretation should generally hold insofar as there were no other relevant policy changes either within Australia, the European Union (EU) or US.”
- [6] “Based on economic modelling, the reforms are estimated to have reduced the likelihood of Australian patents being broader than their international equivalents by between 1.0 and 4.0 percentage points.” / “Given that the narrowing of Australian patents appears to have begun prior to the reforms, caution is warranted in ascribing causality to the reforms.” / “That said, the results were robust to shortening the study's timeframe to focus on the period immediately before and after the reforms.”
- [7] “The analysis uses a modern event study framework.” / “6 It compares firms before and after they receive their first grant and compares them with peers that have not yet received the same right (or which will never receive a right).” / “The peers used for comparison are similar to the focal firms across a range of key attributes - age, size, R&D intensity, financial performance (Return on Assets) and leverage (total liability relative to total assets).”
- [8] “That said, the study design helps distinguish continuation of earlier trends from shifts that emerge after IP engagement.”
- [9] “34 If more innovative firms receive grants (treatment), then their post-grant outcome (patents) can be correlated with their pre-grant characteristics rather than the grant itself To isolate the treatment effect, therefore, it is necessary to compare the outcome of the treated group with that of a control group — matched from the pool of nonparticipants on observable characteristics such as firm size, patent status, industry and geographical location.”
- [10] “Because firms make the decision whether or not to seek IP rights, the results suggest dynamic associations, not definitive causal effects.” / “Firms expecting growth may have stronger incentives to invest in IP, as fixed costs can be spread across expanding sales.”
- [11] “The strategy involves examining the differential behaviour of the same firm selling the same product in different country markets, where the firm faces different shocks.” / “To implement this strategy, in estimating entry and revenue, we include firm-product-year fixed effects.” / “We also include product-market fixed effects; as such, coefficient estimates can be interpreted as the average marginal effect on the dependent variable of log deviations in the independent variable from their average value over the sample in a given product-country market (Fitzgerald & Haller, 2018).”
- [12] “Despite including a rich set of control variables, our analyses may still be affected by endogeneity due to omitted variable bias or reverse causality affecting the relationship between our dependent variables, independent variables and error terms.” / “The empirical approach controls for certain systematic firm-level differences that may affect both a firm's export behaviour and propensity to file trade marks.” / “Nevertheless, due to data limitations, our inability to adequately control for the characteristics of firms' regional divisions could inflate the standard errors for our variables of interest or alter the sign of these variables' coefficients if the measures are linked to a division's trade mark activity and its export behaviour.” / “Reverse causality may also be at play: when a firm anticipates a tariff reduction will occur in a focal export market, pre-empting its own export expansion in that market the firm may file for additional trade marks in the market.”
- [13] “We have included lagged business profitability in our model as the past level of a business's profitability is likely to contribute to its current level of profitability by using its past profit to reinvest in more productive labour and capital.” / “While including the lagged dependent variable is methodologically necessary, it also introduces a risk of new endogeneity in the model.” / “However, the potential endogeneity problem may be alleviated by using statistical techniques such as the Generalised Method of Moments (GMM).” / “Both Difference GMM and System GMM are adopted to address the potential econometric issues related to dynamic panel data and to check the results' robustness.”
- [14] “We have included lagged business profitability in our model as the past level of a business's profitability is likely to contribute to its current level of profitability by using its past profit to reinvest in more productive labour and capital.” / “They are more appropriate than fixed effects and random effects models for regressions concerning the determinants of profitability by controlling for unobserved heterogeneity (i.e. the effect of variables that are not observable in the data but which might have an impact on the dependent variable of interest).” / “Because our dataset is an unbalanced panel dataset with a very large number of groups and relatively small and fixed time periods (T <= 15 with an average of 6), the best available method to handle such data is probably System GMM, which is more effective in dealing with unbalanced panel data than Difference GMM.”
- [15] “These GMM estimators are, under appropriate assumptions, asymptotically unbiased (when N tends to infinity and T is finite).”
- [16] “Further, as reported in Table 17 below, results are similar to the baseline in a model using 2-year lags of all independent variables (Model 22).” / “These findings reduce concerns that our main results are a product of reverse causality (e.g., that anticipating greater competition induced tariff reductions firms both narrow their product range and increase their filing activity to protect core intellectual property).” / “Both Difference GMM and System GMM are adopted to address the potential econometric issues related to dynamic panel data and to check the results' robustness.” / “The estimated coefficients of the lagged dependent variables fall in the range between the OLS and fixed effects estimates, and the Hansen and AR(2) tests have been satisfied under both Difference GMM and System GMM.”
- [17] “Because firms make the decision whether or not to seek IP rights, the results suggest dynamic associations, not definitive causal effects.” / “15 This interpretation should generally hold insofar as there were no other relevant policy changes either within Australia, the European Union (EU) or US.” / “Given that the narrowing of Australian patents appears to have begun prior to the reforms, caution is warranted in ascribing causality to the reforms.” / “Despite including a rich set of control variables, our analyses may still be affected by endogeneity due to omitted variable bias or reverse causality affecting the relationship between our dependent variables, independent variables and error terms.”

*Follow-ups offered:* Can you explain difference-in-differences with a simple example? · How strong is the evidence that IP rights improve productivity? · What did the Raising the Bar evaluation find, and how certain are its conclusions?

### Do small businesses that own trade marks grow faster?

**answer-v4** (partial, 5 claims)

**The evidence points to a growth advantage, but the clearest small-business finding is about the likelihood of growing—not how much faster businesses grow.** Australian small and medium-sized enterprises (SMEs) that file for a trade mark are **16 per cent more likely to achieve positive employment growth over three consecutive years** than peers with no recent filings.[1]

That is a relative difference in the chance of growing: it does **not** mean their employment grows 16 per cent faster, or that their probability of growth is 16 percentage points higher.

### What the research measured
IP Australia’s broader research on intellectual property (IP) rights and SME growth used business-level data from the Australian Bureau of Statistics, covering around **600,000 SMEs active during 2002–2017**.[2] In that study, “high growth” meant employment increasing by at least 20 per cent annually over three consecutive years—a different outcome from simply achieving positive employment growth.[3]

The comparison also matters: the trade mark finding concerns **businesses that filed versus peers with no recent filings**, rather than a strict comparison of all trade mark owners with all non-owners.[1]

### What newer evidence adds
The **2026 Australian IP Report** reports that, after their first trade mark registration, Australian firms had, on average, **78 per cent higher income, 16 per cent higher labour productivity and 0.6 per cent higher total factor productivity** than comparable firms without registered trade marks.[4] The report interprets these results as medium-term revenue gains consistent with businesses scaling up, but this finding covers Australian firms generally, not specifically SMEs.[5]

### How confidently can we interpret this?
Taken together, these findings support a link between trade mark activity and stronger business growth or performance.[1][4] But a predictive relationship is not, by itself, proof that obtaining a trade mark causes the growth: businesses already preparing to expand may also be more likely to seek protection.

So the practical answer is: **SMEs that file for trade marks are more likely to grow their workforce, and newer evidence links registration with stronger business performance—but these passages do not establish exactly how much faster small trade mark owners grow, or how much of the difference is caused by the trade mark itself.**[1][4]

Sources:

- [1] “Australian small and medium enterprises (SMEs) that file for a trade mark are 16% more likely to achieve positive employment growth over 3 consecutive years than peers with no recent filings.”
- [2] “The study used business microdata provided in the Business Longitudinal Analysis Data Environment. Administered by the Australian Bureau of Statistics, this data covers the full population of Australian businesses active since 2002. The present study focused on around 600,000 SMEs active over the period 2002 to 2017.”
- [3] “High-growth SMEs were identified as those that achieve at least 20% annual growth in employment over 3 consecutive years.”
- [4] “After their first trade mark registration, Australian firms outperform comparable firms without registered trade marks, with income on average 78% higher, labour productivity 16% higher and total factor productivity 0.6% higher after grant.”
- [5] “After their first trade mark registration, Australian firms outperform comparable firms without registered trade marks” / “The results point to medium-term revenue gains consistent with firm scaling (Nguyen, 2026).”

*Not covered:* The passages do not quantify how much faster employment or revenue grows specifically for small trade mark owners compared with non-owners.; The passages do not establish how much of the SME growth difference is caused by trade mark protection rather than other differences between businesses.

*Follow-ups offered:* What is the difference between predicting growth and causing it? · Are SMEs with patents and designs also more likely to grow? · How common is trade mark ownership among Australian SMEs?

**answer-v5** (complete, 7 claims)

**Small businesses that file for trade marks are more likely to grow—but that does not necessarily mean trade mark ownership itself makes them grow faster.** IP Australia’s research found that Australian small and medium-sized enterprises (SMEs) filing for a trade mark were **16% more likely to achieve positive employment growth over three consecutive years** than peers without recent filings. [1]

That is a finding about the **likelihood of increasing staff numbers**, not a finding that employment grew 16% faster. It also concerns trade mark **filing activity**, rather than ownership alone. [1]

### What supports that finding?
The SME growth research described in the 2022 Australian IP Report examined around **600,000 Australian SMEs active between 2002 and 2017**, using business-level data from the Australian Bureau of Statistics’ Business Longitudinal Analysis Data Environment. [2] It found that SMEs filing for registered intellectual property rights—patents, trade marks or designs—were more likely to achieve high growth and employ more people than peers without recent filings. [3]

More recent evidence also points to stronger business performance after trade mark registration. The **2026 Australian IP Report** reports that, after their first trade mark registration, Australian firms had average income **78% higher** and labour productivity **16% higher** than comparable firms without registered trade marks; the report interprets the results as consistent with firms expanding in scale. [4] Those results concern Australian firms generally, not specifically small businesses. [5]

### How confidently should we interpret this?
The useful distinction is between a **signal of growth** and a **cause of growth**. A relationship between filing and later growth does not, by itself, establish how much growth the trade mark caused: businesses preparing to expand may also be more likely to seek protection. The publications themselves recognise that differences between intellectual property owners and non-owners could reflect either the resources larger firms have to obtain rights or subsequent growth among firms that file. [6]

So the practical reading is: **trade mark filing is a useful indicator of a small business’s growth prospects**, rather than a guarantee that obtaining a trade mark will deliver faster growth. [7]

Sources:

- [1] “Research by IP Australia estimated that Australian small and medium enterprises (SMEs) that file for a trade mark are 16% more likely to achieve positive employment growth over 3 consecutive years than peers with no recent filings.”
- [2] “The study used business microdata provided in the Business Longitudinal Analysis Data Environment.” / “Administered by the Australian Bureau of Statistics, this data covers the full population of Australian businesses active since 2002.” / “The present study focused on around 600,000 SMEs active over the period 2002 to 2017.”
- [3] “IP Australia has conducted research to understand the role of registered IP rights (patents, trade marks and designs) in the growth of Australian small and medium enterprise (SMEs).” / “The results reveal that Australian SMEs that file for registered IP rights are more likely to achieve high growth and employ more people than their peers with no recent filings.”
- [4] “` After their first trade mark registration, Australian firms outperform comparable firms without registered trade marks, with income on average 78% higher, labour productivity 16% higher and total factor productivity 0.6% higher after grant.” / “The results point to medium-term revenue gains consistent with firm scaling (Nguyen, 2026).”
- [5] “` After their first trade mark registration, Australian firms outperform comparable firms without registered trade marks, with income on average 78% higher, labour productivity 16% higher and total factor productivity 0.6% higher after grant.”
- [6] “This indicates that larger businesses tend to own IPRs, which could be because it requires resources to create and maintain IPRs, or because young or small businesses that file IPRs grow to be larger and live for longer due to their IPR portfolios.”
- [7] “At the firm level, trade mark filing activity is a significant forward predictor of firm growth.” / “Research by IP Australia estimated that Australian small and medium enterprises (SMEs) that file for a trade mark are 16% more likely to achieve positive employment growth over 3 consecutive years than peers with no recent filings.”

*Follow-ups offered:* Why might trade marks help a business grow? · What counts as a high-growth small business? · Are trade mark owners more likely to become exporters?

### What is patent pendency and why does it matter?

**answer-v4** (complete, 10 claims)

**Patent pendency is the time a patent application takes to reach an outcome**—such as being granted, lapsing or being refused; studies focused on granted patents often use it to mean the time from filing to grant.[1] It matters because that time reflects both processing delays and choices applicants make about when to progress their applications.[2]

## How is it measured?

The 2014 report distinguishes two main measures:[3]

- **Entry pendency:** follow applications filed in the same month and measure how long they take to reach an outcome.[3]
- **Exit pendency:** look at applications reaching an outcome in the same month and measure how long they spent in the system.[3]

In everyday terms, entry pendency asks, “What happened to the applications that came in together?” Exit pendency asks, “How long did the applications finishing now take?”

There is an important measurement catch: recent filing groups still contain unfinished applications, so their measured time to grant can be understated.[4] In plain English, the quick cases finish first; looking only at those can make the whole group appear faster than it eventually proves to be.

## Why does it matter?

**1. Applicants and the office experience the wait differently.** Applicants generally think of pendency as time to grant, while IP Australia also considers the time until an application leaves its inventory, whatever the outcome.[2] Grant is an important milestone: the 2023 Australian IP Report states that a patent is enforceable in Australia only after it has been granted.[5]

**2. Not all elapsed time is an office delay.** Australia operates a deferred examination system, in which applicants must request examination; the 2014 process description says applicants could wait up to five years, although the office could direct them to request it earlier.[6] The 2015 report identifies the period from the examination request to the first report as the only main stage solely under IP Australia’s control.[7] So total pendency should not be read simply as a measure of examiner speed.[6][7]

**3. Faster is not equally valuable to every applicant.** The 2025 report finds that, for large businesses, faster office processing is linked to a greater likelihood of commercialising a patent and undertaking follow-on innovation.[8] Small businesses are more likely to delay examination, more likely than large businesses to renew patents they have delayed, and less affected by office-side delays in their long-term commercialisation and follow-on innovation outcomes.[9] These links should not be read as a guarantee that speeding up—or delaying—any individual application will improve its outcome.

**The practical takeaway:** pendency is useful, but it needs context—what outcome is being measured, which applications are included, and who controls the timing.[1][3][7] The 2025 report’s overall reading is that faster processing is likely to benefit the economy **provided applicants retain sufficient flexibility to influence application timeframes**.[10]

Sources:

- [1] “The time to terminal disposal (sealed, lapsed, refused, etc) for all applications terminating in the same month.” / “Average pendency period is defined as the number of years between grant year and filing year.”
- [2] “For applicants pendency is generally seen as the time taken for a grant; for IP Australia it is the time taken for application to get off the inventory.” / “Some pendency can also be attributed to applicant behaviour as not all applicants are keen to proceed with timely examinations”
- [3] “Exit Pendency: The time to terminal disposal (sealed, lapsed, refused, etc) for all applications terminating in the same month.” / “Entry Pendency: The time to terminal disposal for all applications that are filed in the same month.”
- [4] “A drawback for this measure is censoring as the measure is not accurate until a large majority of applications are granted.” / “due to the censoring effect all indicators may be understated for after 2008.”
- [5] “A patent is enforceable in Australia only after it has been granted.”
- [6] “IP Australia operates a deferred examination system, where applicants have to request examination. Applications enter the office and applicants have up to five years to file their exam request, but the office can direct applicants to file this request.”
- [7] “The second stage, from exam request to first report, is the only stage that IP Australia has sole control over.”
- [8] “Faster processing is linked to a greater likelihood of the business commercialising a patent and more follow-on innovation by the business building on their patent.”
- [9] “Small businesses are more likely than large businesses to delay the examination process.” / “Compared to large businesses, small businesses are more likely to renew a patent that they have delayed.” / “Small businesses are less impacted by office-side delays in the likelihood that they will commercialise a patent as a product or engage in follow-on innovation over the long term.”
- [10] “This study's findings imply that faster processing of patent applications is likely to deliver tangible benefits for Australia's economy so long as applicants retain sufficient flexibility to influence application timeframes.”

*Follow-ups offered:* Why might a small business benefit from delaying examination? · How does Australian patent pendency compare with other countries? · How has patent pendency changed over time?

**answer-v5** (complete, 19 claims)

**Patent pendency is the time a patent application spends waiting for an outcome.** For applicants, that usually means the time to grant; for the patent office, it can mean the time until an application leaves its pending inventory, whether it is granted, lapses or is refused. [1] It matters because delays can affect applicants’ commercial decisions and create uncertainty for competitors deciding where to invest or innovate. [2]

## What exactly is being timed?

There is more than one pendency measure, so it helps to ask where the clock starts and stops:

- **Filing to grant:** a 2024 research paper cites IP Australia guidance that this typically takes **3 to 5 years** in Australia. [3]
- **Examination request to acceptance:** the 2025 Australian IP Report gives a median of **1.3 years**, using 2020 as the latest complete data year. [4] This is a different interval: under the process described in the 2014 report, applicants request examination after filing, and acceptance precedes an opposition period and eventual grant. [5]

Researchers also distinguish between **exit pendency**, which groups applications by when they reach an outcome, and **entry pendency**, which groups them by when they were filed. [6] Recent filing groups need particular care: their slower applications may still be pending, making the observed time to grant look shorter than it eventually will be. [7]

## A long wait is not necessarily an office backlog

Australia operates a deferred examination system, in which applicants must request examination rather than having it begin automatically on filing. [8] The 2025 report finds that differences in application timeframes are driven largely by applicant behaviour and preferences. [9]

Office capacity can also matter: the 2014 backlog study associated earlier inventory growth primarily with low examiner numbers between 2003 and 2006, alongside rising application numbers. [10] In other words, pendency can reflect both applicants’ choices and office processing—not just one or the other. [11]

## Why does it matter economically?

**For applicants, faster is often better—but not always.** Applicants who use the freely available options to accelerate examination tend to be more likely to renew, commercialise and build on their patents. [12] For large businesses, faster office processing is also linked to greater commercialisation and follow-on innovation. [13] Small innovators are different: delays tend to predict stronger post-grant outcomes, and they may need to establish priority claims before seeking investment and resources. [14] These are reported relationships; they should not be read as proof that choosing to wait, or choosing to accelerate, will itself improve a particular applicant’s outcome.

**For competitors, uncertainty can hold back innovation.** Until grant, rivals may be unsure whether a patent will be granted and how much technological space it will cover, potentially discouraging investment, research and development, or market entry. [15] The study summarised in the 2025 report found that grant delays tend to slow and narrow rivals’ follow-on innovation, as reflected in their later patenting. [16] An equivalent patent granted overseas can partly reduce that uncertainty. [17]

Those findings draw on a quantitative study of **316,077 standard patents granted in Australia from 2004 to 2016**, excluding divisionals, linked with overseas patent and other data. [18]

The practical takeaway is that pendency is not simply a speed measure: interpreting it requires knowing **which stage is being timed, what is driving the delay, and whose outcomes are affected**. [19]

Sources:

- [1] “For applicants pendency is generally seen as the time taken for a grant; for IP Australia it is the time taken for application to get off the inventory.” / “Exit Pendency: The time to terminal disposal (sealed, lapsed, refused, etc) for all applications terminating in the same month.”
- [2] “For large businesses, faster office processing - fewer delays caused by the patent office in examination - has a strong impact in enhancing economic outcomes.” / “Faster processing is linked to a greater likelihood of the business commercialising a patent and more follow-on innovation by the business building on their patent.” / “Patent grant delays create uncertainty about whether a patent will be granted and its eventual scope (the extent of technological space that will be excluded from development by others due to the patent right).” / “This uncertainty can deter third parties from investing in certain technologies, undertaking R&D, or entering specific markets.”
- [3] “According to guidance from IP Australia, there is typically a 3 to 5-year lag between the filing date of a patent application and its granting in Australia.”
- [4] “The median time from when an applicant requests IP Australia to commence substantive examination of their patent to when the patent is accepted for grant is 1.3 years, as of 2020 (latest complete data).”
- [5] “IP Australia operates a deferred examination system, where applicants have to request examination.” / “Applications enter the office and applicants have up to five years to file their exam request, but the office can direct applicants to file this request.” / “Once an application is accepted by the office, it enters a three month opposition period, where third parties can oppose the application.” / “If the application is unopposed or makes it through an opposition procedure, the applicant has to pay a granting fee before the application is granted.”
- [6] “Exit Pendency: The time to terminal disposal (sealed, lapsed, refused, etc) for all applications terminating in the same month.” / “Entry Pendency: The time to terminal disposal for all applications that are filed in the same month.”
- [7] “A drawback for this measure is censoring as the measure is not accurate until a large majority of applications are granted.” / “Furthermore, from Appendix Table A9, if we only look at filings from the early years of the 2001-2020 period we can say that the pendency period at EPO is probably closer to 6 years, since more recent grants are likely those which are granted faster.”
- [8] “IP Australia operates a deferred examination system, where applicants have to request examination.”
- [9] “There is significant variation in patent application timeframes, driven largely by applicant behaviour and preferences.”
- [10] “The growth in the early 2000s is correlated with the increasing number of applications filed every year but primarily with the low number of examiners on staff between 2003 and 2006.”
- [11] “Some pendency can also be attributed to applicant behaviour as not all applicants are keen to proceed with timely examinations, and the deferred examination system is geared toward providing for such applicants.” / “The growth in the early 2000s is correlated with the increasing number of applications filed every year but primarily with the low number of examiners on staff between 2003 and 2006.”
- [12] “The Motu/EPFL study found that applicants who speed up examination using IP Australia's freely available options for doing so tend to experience better post-grant outcomes.” / “They are more likely to renew, commercialise and build on their patents.”
- [13] “For large businesses, faster office processing - fewer delays caused by the patent office in examination - has a strong impact in enhancing economic outcomes.” / “Faster processing is linked to a greater likelihood of the business commercialising a patent and more follow-on innovation by the business building on their patent.”
- [14] “For small innovators, who may need to establish priority claims on their inventions before searching for investment and resources, delays tend to predict stronger post-grant outcomes.”
- [15] “Patent grant delays create uncertainty about whether a patent will be granted and its eventual scope (the extent of technological space that will be excluded from development by others due to the patent right).” / “This uncertainty can deter third parties from investing in certain technologies, undertaking R&D, or entering specific markets.”
- [16] “The Motu/EPFL study found that patent grant delays tend to slow and narrow follow-on innovation by the applicant's rivals, as reflected in their future patenting activity.”
- [17] “In addition, the impact of delays is partially mitigated when an equivalent to the Australian patent (a patent for the same or similar invention) is granted overseas.” / “The foreign grant likely reduces uncertainty about the eventual scope of the right - the amount of technological space likely to be excluded from rival development.” / “Competitors can then make better informed technology and market investments.”
- [18] “The study involved a quantitative analysis of the nature and impact of delays across 4 post-grant outcomes:” / “To study used data on 316,077 standard patents granted by IP Australia from 2004 to 2016 (excluding divisionals) as well as data on equivalent patents (for the same or similar inventions) filed in other jurisdictions.” / “The data was combined from several sources, including IP Australia's IPRAPID dataset, the PATSTAT global patent database, PatentsView data from the United States Patent and Trade Mark Office (USPTO), and IPRoduct, a dataset linking patents to products based on 'virtual patent markings,' webpages that list the patents related to a firm's products.”
- [19] “Exit Pendency: The time to terminal disposal (sealed, lapsed, refused, etc) for all applications terminating in the same month.” / “Entry Pendency: The time to terminal disposal for all applications that are filed in the same month.” / “There is significant variation in patent application timeframes, driven largely by applicant behaviour and preferences.” / “For large businesses, faster office processing - fewer delays caused by the patent office in examination - has a strong impact in enhancing economic outcomes.” / “In contrast, delays appear to be particularly beneficial for small innovators.” / “The Motu/EPFL study found that patent grant delays tend to slow and narrow follow-on innovation by the applicant's rivals, as reflected in their future patenting activity.”

*Follow-ups offered:* Why might delays benefit small innovators but not large businesses? · How do researchers separate applicant delays from office delays? · How does Australian patent pendency compare with other countries?

### How have patent applications in Australia changed over the last decade?

**answer-v4** (partial, 13 claims)

**Patent applications in Australia have had an uneven decade, rather than a steady rise.** Standard applications grew by 10 per cent in 2015, while the latest overall annual result in the supplied passages is a 3.3 per cent fall in 2024; that recent decline came from overseas applicants, while Australian-resident applications edged up.[1][2][3]

The passages provide useful snapshots, but not a complete annual series through 2025, so they do not establish the exact change over the full decade.

### Overall filings: overseas applicants drive the recent decline

In 2015, IP Australia received **28,605 standard patent applications**, up 10 per cent on 2014, following a spike in 2013 and a dip in 2014 associated with the *Raising the Bar* legislative changes.[1]

By 2024, non-residents accounted for **91.5 per cent** of standard patent filings, and the decline that year was entirely attributable to reduced non-resident filings.[3] The 2025 report identifies reduced applications from the United States and reduced patenting across health technology fields as the main drivers of the overall 3.3 per cent fall.[2]

### Australian applicants: recent stability, with a growing role for smaller businesses

Australian-resident standard applications rose **2.4 per cent to 2,556 in 2023**, then **0.9 per cent to 2,578 in 2024**.[4][5] The reports describe this as resilience despite tighter financial and economic conditions, rather than a substantial domestic downturn.[2][4]

Small and medium-sized enterprises (SMEs) have become more prominent: their share of resident filings increased from **57.9 per cent in 2014 to 62.9 per cent in 2023**.[6] In 2024, filings from Australian SMEs grew by **1.9 per cent**, and those from individuals by **3.9 per cent**; together these groups accounted for **87.2 per cent** of resident filings, while applications from large firms fell by **6.9 per cent**.[7]

### Overseas origins: the United States remains dominant, while China has grown

The United States remained the largest overseas source in 2024, with US applicants named on **42.7 per cent** of all standard filings, followed by China at **8.5 per cent**.[8] US filings fell for a second consecutive year in 2024, down **6.2 per cent**, whereas China-origin filings reached a record, rising **5.2 per cent**.[8]

China’s longer-term growth has slowed markedly: the 2025 report puts average annual growth at **7 per cent over the five years to 2024**, compared with **30 per cent over the five years to 2019**.[9]

### Technology mix: health remains central

The latest technology figures show that pharmaceuticals, medical technology and biotechnology together accounted for **33.3 per cent of standard complete filings in 2025**.[10] The 2026 report describes life sciences as having gradually increased their share over the preceding decade, despite the recent annual fluctuations.[10]

### Provisional applications tell a different story

Provisional applications establish an early priority date and give applicants 12 months to decide whether to file a complete application, but they provide no enforceable protection.[11] They numbered **5,343 in 2015**, compared with **4,244 in 2023**, although 2023 itself saw a 5.2 per cent increase.[12][13] The 2024 report attributes the longer-term decline mainly to fewer filings by individuals, with filings by large organisations and SMEs relatively stable.[13]

Taken together, the evidence suggests a changing pattern—not simply more or fewer applications: recent overall weakness has been overseas-led, domestic filings have held up, smaller applicants have become more prominent, and health technologies remain central.[2][3][5][6][7][10]

Sources:

- [1] “IP Australia received 28 605 standard patent applications in 2015, an increase of 10 per cent from 2014.” / “Applications for patents returned to their normal growth trend after the sharp increase in 2013 caused by Raising the Bar which was followed by a subsequent dip in 2014.”
- [2] “Filings by Australian residents were stable, despite tight financial and economic conditions.” / “Overall filings fell by 3.3%, driven by reduced applications from the United States, and reduced patenting across health technology fields.”
- [3] “The decline in standard patent filings in 2024 was entirely attributed to reduced filings by non-residents (entities outside Australia). These account for 91.5% of annual standard patent filings in Australia.”
- [4] “Standard patent applications by residents increased by 2.4% in 2023, to 2,556 in total” / “Domestic patenting in Australia, however, has not significantly declined.”
- [5] “In contrast, applications by Australian residents increased by 0.9%, to 2,578 in total”
- [6] “The SME share of resident filings has steadily increased over the past decade, from 57.9% in 2014 to 62.9% in 2023”
- [7] “in 2024 standard patent filings from Australian SMEs and individuals expanded, by 1.9% and 3.9%. Filings from these applicants now comprise 87.2% of total resident filings. Applications by large firms fell by 6.9% from their level in 2023.”
- [8] “the lead overseas origins for standard patent filings in Australia are the United States (US residents are named as applicants on 42.7% of total filings), China (8.5%)” / “In 2024, US filings fell for the second consecutive year, down by 6.2% from 2023 level.” / “China-origin filings reached a new record level, rising by 5.2% on their previous record in 2023.”
- [9] “Over the 5 years to 2024, filings from China have grown at an annual average rate of 7%. This represents a significant tapering from the 30% average annualised growth over the 5 years to 2019.”
- [10] “In 2025, pharmaceuticals (3,715 applications), medical technology (3,331) and biotechnology (3,073) together accounted for 33.3% of all standard complete filings.” / “Over the past decade, the share of life sciences technologies has gradually deepened and remained structurally elevated relative to other fields.”
- [11] “Filing a provisional patent gives applicants 12 months to decide whether to file a complete patent application. Provisional applications are not subject to substantive examination and offer no enforceable protection.” / “However, they establish the priority date that will be used to identify prior art relevant to assessing the complete patent application”
- [12] “In 2015, however, the number of filings for provisional applications increased one per cent to 5 343.”
- [13] “In 2023, the number of provisional filings totalled 4,244, up 5.2% from their level in 2022.” / “The decline in provisional filings is mostly driven by a reduction in filings by individual applicants. Filings by large organisations and SMEs have remained relatively stable over the past decade.”

*Not covered:* The supplied passages do not provide a complete annual application series or an overall 2025 standard-application total, so an exact latest-decade change cannot be established.; The latest provisional-application figures supplied are for 2023; the passages also do not provide a full decade-long account of innovation patent applications.

*Follow-ups offered:* Why have smaller businesses become more prominent in domestic patent filings? · What is behind the changes in applications from China and the United States? · How much can patent application counts tell us about innovation?

**answer-v5** (complete, 17 claims)

**Patent applications in Australia have grown modestly over the past decade, but not steadily.** Standard patent applications rose from 28,605 in 2015 to 30,348 in 2025—an increase of about 6% across the decade, calculated using the resident and non-resident totals reported for 2025. [1]

The latest picture is one of **broadly stable total filings, but stronger growth from Australian applicants**: resident applications increased by 9.0% in 2025, while non-resident applications fell by 1.3%. [2]

### A modest upward trend, with interruptions

These figures concern **standard patent applications**, rather than patents granted. Some useful milestones are:

| Year | Standard patent applications in Australia | What changed |
|---|---:|---|
| 2015 | 28,605 | Up 10% from 2014. [3] |
| 2019 | 29,758 | Down 0.7% from 2018. [4] |
| 2020 | 29,293 | Down 2% from 2019, but still above the preceding 10-year annual average. [5] |
| 2025 | 30,348 | Calculated by adding 2,810 resident and 27,538 non-resident applications; total filings were broadly stable. [2] |

The starting point matters: the 2015 increase followed unusually high filings ahead of the *Raising the Bar* legislative reforms in 2013 and a subsequent fall in 2014. The reports describe applications as returning to a mild growth trend after that disruption. [6]

Not every fall has the same explanation. The small decline in 2019 was largely attributed to fewer divisional applications—applications containing subject matter from an earlier application. [7] The 2020 decline occurred during the COVID-19 pandemic, but the report cautioned that the effects of that economic shock might take longer to appear because research and development can influence patenting over an extended period. [8]

### Australian and overseas applicants have followed different paths

**Overseas applicants still account for about nine in ten filings.** Non-residents made up 91% of applications in 2016 and 90.7% in 2025, so changes in their activity have considerable influence on the overall total. [9]

Domestic applications have recently been more resilient:

- **2023:** Australian resident applications increased by 2.4% to 2,556. [10]
- **2024:** They increased by another 0.9% to 2,578, while the overall decline in filings was entirely attributable to non-residents. [11]
- **2025:** They rose by 9.0% to 2,810, lifting the resident share to 9.3%—its highest level since 2021. [12]

There has also been a shift within domestic filing activity towards smaller applicants: small and medium-sized enterprises (SMEs) increased their share of resident applications from 57.9% in 2014 to 62.9% in 2023. [13] In 2024, filings from SMEs and individuals grew by 1.9% and 3.9%, respectively, while filings from large firms fell by 6.9%. [14]

### What the trend tells us—and what it does not

Taken together, the reports suggest **modest long-term growth, with recent domestic strength partly offsetting weaker overseas filings**, rather than a uniform rise across applicants. [15]

Two cautions help interpret the figures:

- **Patent filings are not a broad measure of all business innovation.** The 2026 report stresses that Australian resident patenting reflects a relatively small group of research-intensive, technologically specialised firms, rather than business activity generally. [16]
- **Australian filings can reflect earlier decisions.** In 2024, 70% of applications came through the Patent Cooperation Treaty (PCT) route; for these applicants, the average interval between first filing globally and entering Australia was 18 months. The report therefore cautions that those filings may reflect innovation investments made in 2023 or earlier. [17]

Sources:

- [1] “The US, Japan, Germany and the UK filed 63 per cent of patents in Australia Patent applications: IP Australia received 28 605 standard patent applications in 2015, an increase of 10 per cent from 2014.” / “Australian applicants filed 2,810 standard complete applications in 2025, up from 2,578 in 2024 - an increase of 9.0%.” / “Non-resident filings declined modestly in 2025, from 27,909 in 2024 to 27,538 (-1.3%).”
- [2] “While non-resident applicants continue to make up the majority of standard patent filings, Australian resident applications increased in 2025, against broadly stable total filings.” / “Australian applicants filed 2,810 standard complete applications in 2025, up from 2,578 in 2024 - an increase of 9.0%.” / “Non-resident filings declined modestly in 2025, from 27,909 in 2024 to 27,538 (-1.3%).”
- [3] “The US, Japan, Germany and the UK filed 63 per cent of patents in Australia Patent applications: IP Australia received 28 605 standard patent applications in 2015, an increase of 10 per cent from 2014.”
- [4] “Standard patent applications: In 2019, a total of 29 758 applications for standard patents were filed, a 0.7 per cent decrease from their level in 2018 (Figure 1).”
- [5] “In 2020, IP Australia received 29 293 standard patent applications, including divisional applications – a 2 per cent decrease compared to 2019 (Figure P1), but still higher than the 10-year annual average of 28 308 applications.”
- [6] “Applications for patents returned to their normal growth trend after the sharp increase in 2013 caused by Raising the Bar which was followed by a subsequent dip in 2014.” / “A surge in patenting in 2013 anticipated the implementation of the Raising the Bar legislative reforms announced in 2012, which raised the quality threshold for patent grants.3 Growth in applications prior to the reform was followed by a large decrease in applications in 2014, before returning to their overall mild growth trend until 2019.”
- [7] “The fall can be largely attributed to a decrease in divisional applications-patent applications which contain subject matter from previously filed applications.”
- [8] “In 2020, IP Australia received 29 293 standard patent applications, including divisional applications – a 2 per cent decrease compared to 2019 (Figure P1), but still higher than the 10-year annual average of 28 308 applications.” / “This filing activity occurred despite the considerable economic impact of the COvID-19 pandemic.” / “Patents are a partial indicator of the output or "success" of research and development (R&D) activity and although R&D investment typically occurs early in the life of a research project it also tends to produce long-run effects on firm patenting.” / “As such, the effects of the economic crisis in 2020 may not be fully observed until beyond 2021.2”
- [9] “Filings by non-residents in Australia declined by two per cent to 25 774, accounting for 91 per cent of filings.” / “As a result, the nonresident share eased slightly to 90.7%.”
- [10] “Standard patent applications by residents increased by 2.4% in 2023, to 2,556 in total (Figure 3.5).”
- [11] “The decline in standard patent filings in 2024 was entirely attributed to reduced filings by non-residents (entities outside Australia).” / “In contrast, applications by Australian residents increased by 0.9%, to 2,578 in total (Figure 2.2).”
- [12] “Australian applicants filed 2,810 standard complete applications in 2025, up from 2,578 in 2024 - an increase of 9.0%.” / “As a share of total standard complete filings, residents accounted for 9.3%, up from 8.5% in 2024 and the highest share since 2021.”
- [13] “60 The SME share of resident filings has steadily increased over the past decade, from 57.9% in 2014 to 62.9% in 2023, and private inventors (individuals) account for an additional 22.1%.”
- [14] “Consistent with these trends, in 2024 standard patent filings from Australian SMEs and individuals expanded, by 1.9% and 3.9%.” / “Applications by large firms fell by 6.9% from their level in 2023.”
- [15] “The US, Japan, Germany and the UK filed 63 per cent of patents in Australia Patent applications: IP Australia received 28 605 standard patent applications in 2015, an increase of 10 per cent from 2014.” / “While non-resident applicants continue to make up the majority of standard patent filings, Australian resident applications increased in 2025, against broadly stable total filings.” / “Australian applicants filed 2,810 standard complete applications in 2025, up from 2,578 in 2024 - an increase of 9.0%.” / “Non-resident filings declined modestly in 2025, from 27,909 in 2024 to 27,538 (-1.3%).”
- [16] “Unlike trade marks or designs, patenting in Australia is not a broad barometer of business dynamism and commercial activity.” / “Instead, resident patenting reflects activity by a relatively small subset of firms engaged in R&D-intensive and technologically specialised innovation.”
- [17] “In 2024, 70% of standard patent applications in Australia were filed via the PCT route, down from 73% in 2023.” / “On average, for applicants who file in Australia through the PCT system, there is an 18-month delay between when they first file a patent application globally and when they file that patent in Australia (it enters Australian 'national phase').” / “As such, PCT applications in 2024 may reflect innovation investments made over 2023 or earlier.”

*Follow-ups offered:* Which countries have driven changes in overseas patent filings? · Which technology fields have grown most strongly? · Why are SMEs accounting for a larger share of domestic patent applications?

### What did the research find about the gender gap in IP?

**answer-v4** (complete, 11 claims)

The research found a persistent gender gap in patenting: women’s participation was rising, but women remained under-represented, and more applications naming women did not necessarily mean more women entering the inventor pool.[1][2][3] Importantly, the reports found no evidence of systematic productivity differences between women and men in creative and innovative work.[4]

## Participation was increasing—but the gap remained

The latest figures in these passages are from the **2023 Australian IP Report**, covering 2022:

- **26 per cent of the international patent applications from Australia covered by the report named at least one woman inventor**, up three percentage points over the three years to 2022.[2]
- **Women made up 14.6 per cent of unique Australian inventors** in those applications—unchanged from 2021.[1]
- Using the rounded figure of 15 per cent, the report put Australia’s share of women inventors **two percentage points below the international average**.[5]

Those measures answer different questions: whether an application includes a woman, and how many individual inventors are women. The report suggested that the combination could reflect existing women inventors patenting more intensively, rather than substantial growth in the number of women inventors; increasing participation was occurring in mixed-gender teams.[3]

There was also longer-term progress: women’s share of unique Australian inventors listed on patent applications in Australia rose from about 4 per cent in 1980 to around 12 per cent in 2016.[6] That is a different application population from the international figures above, so it should not be read as a directly comparable series.

## The gap varied substantially by technology

In 2022, women were named on 61 per cent of the international applications in biotechnology, 59 per cent in both organic fine chemistry and pharmaceuticals, and 56 per cent in both analysis of biological materials and food chemistry.[7] These are shares of **applications with a woman inventor**, not women’s shares of all inventors.

The report identified several possible contributors to the gap: differences across research fields, the nature of women’s research, women receiving less credit for scientific output, and disparities in research funding.[8] These are potential explanations—not a quantified breakdown of how much each factor contributes.

## Greater representation was associated with innovation benefits

The research did **not** suggest that women’s under-representation reflected lower innovative ability: the report cited evidence of no systematic productivity differences between women and men, and evidence that gender-diverse teams tend to produce more radical innovations and higher-impact scientific ideas.[4]

IP Australia also compared Australian businesses of similar size within the same industry to examine women’s representation and innovation performance.[9] It found:

- **Lower research intensity, but more efficient conversion into patents:** women’s representation in leadership and science, technology, engineering and mathematics (STEM) roles was associated with lower research and development (R&D) intensity; among R&D businesses, a 10 percentage point increase in women’s leadership share was associated with a 0.1 per cent increase in efficiency in converting R&D expenditure into patents.[10]
- **Broader IP holdings in start-ups:** women’s participation in management was associated with increased overall intellectual property (IP) holdings, including trade marks, designs and plant breeder’s rights, with increases of around 1 per cent or less for each 10 percentage point increase in women’s participation.[11]

These are associations, not proof that changing a team’s gender composition causes the observed outcomes. Taken together, the evidence points to an important distinction: **a persistent participation gap can coexist with strong innovative performance by women and gender-diverse teams**.[1][4][10]

Sources:

- [1] “At the same time, the share of unique women inventors on Australian PCT applications remained relatively constant. In 2022, women constituted 14.6% of Australian inventors, the same level as in 2021.”
- [2] “in the three years to 2022, the share of PCT applications from Australia with at least one woman inventor increased by three percentage points to 26%”
- [3] “Data on Australians' patenting activity suggests that growth in women's participation is occurring in mixed-gender teams.” / “An alternative reading of these trends is that women inventors are filing patents more intensively without significant growth in the women inventor pool.”
- [4] “Evidence shows there are no systematic productivity differences between women and men in creative and innovative endeavours 17 . However, gender diverse teams tend to produce more radical innovations and higher-impact scientific ideas”
- [5] “Women account for 15% of unique inventors named on PCT applications from Australia. This represents a participation rate 2 percentage points lower than the international average”
- [6] “Female inventors comprised around 12% of unique Australian inventors listed on patent applications in Australia in 2016, up from 4% in 1980.”
- [7] “In 2022, women inventors were named on around half of PCT applications in Biotechnology (61%), Organic fine chemistry (59%), Pharmaceuticals (59%), Analysis of biological materials (56%) and Food chemistry (56%).”
- [8] “Representation of women on patents varies across technology fields.” / “Other factors that may contribute to the gender patent gap include the nature of women's research 13 , under-crediting of women in science output 14 , and disparity in research funding”
- [9] “IP Australia's study modelled the relationship between women's representation in Australian businesses and their innovation investments and performance. The analysis compared businesses of similar size operating within the same industry.”
- [10] “Women's representation in leadership and STEM was associated with lower R&D intensity.” / “Nevertheless, among R&D businesses, those with a greater share of women in leadership were more efficient in converting R&D investment into patents 25 . For every 10 percentage point increase in the women's share of leadership, efficiency in converting R&D expenditure into patents increased by 0.1%.”
- [11] “Women's participation in the management team of start-ups was associated with increased overall IP holdings. Separately, it predicted increased holdings of trade marks, designs and PBRs. The effect was incremental, at around 1% or less for every 10 percentage point increase in women participation”

*Follow-ups offered:* What does the evidence say about barriers to women entering the patent system? · How should we interpret the finding about lower R&D intensity but greater patenting efficiency? · What did the research find about cultural diversity and innovation?

**answer-v5** (complete, 14 claims)

The research found a **persistent gender gap in patenting: women’s participation was increasing, but women remained under-represented, and more applications involving women did not necessarily mean more women entering the inventor pool**. The findings provided are mainly about patents, rather than intellectual property (IP) rights generally.[1]

### How large was the gap?
The 2023 Australian IP Report presents two different measures for 2022:
- **Share of applications:** 26 per cent of international patent applications from Australia filed through the Patent Cooperation Treaty (PCT) route named at least one woman inventor.[2]
- **Share of individual inventors:** women accounted for 14.6 per cent of Australian inventors on those applications, unchanged from 2021. Rounded to 15 per cent, this was two percentage points below the international average.[3]

These measures answer different questions: an application can include a woman without women making up a large share of its inventor team.

### Participation was growing—but entry remained a concern
In the three years to 2022, the share of Australian PCT applications naming at least one woman rose by three percentage points, to 26 per cent.[2] The reports link the growth to **mixed-gender teams**; the 2022 report suggests this could reflect changing team composition or women being more likely to receive recognition for their contributions.[4]

However, because women’s share of individual inventors remained relatively constant, the 2023 report offers another possible explanation: existing women inventors may have been filing more intensively, without substantial growth in the pool of women inventors.[5] It also cites US research finding that the gender gap was greatest at inventors’ first contact with the patent system; among previous patent inventors, the gap between women and men patenting again within five years was only 6 per cent.[6] That finding concerns the US, not a direct estimate for Australia.[7]

### What might explain the gap?
The evidence does **not** point to systematically lower productivity among women in creative and innovative work.[8] Instead, the report identifies several possible contributors:
- **Differences across technology fields.** In 2022, women were named on 61 per cent of Australian PCT applications in biotechnology, 59 per cent in both organic fine chemistry and pharmaceuticals, and 56 per cent in both analysis of biological materials and food chemistry.[9]
- **The nature of women’s research, under-crediting of women’s contributions, and unequal research funding.** These are identified as possible contributors, rather than quantified explanations of the Australian gap.[10]
- **Access to follow-on investment.** The report notes that women entrepreneurs reportedly receive less funding, on less favourable terms, for further research and development.[11]

### Why does this matter for innovation?
The report summarises evidence that gender-diverse teams tend to produce more radical innovations and higher-impact scientific ideas.[12] Its Australian business research also found that women’s representation in leadership was associated with lower research spending intensity but greater efficiency in converting research and development into IP.[13] That is an association—not proof that leadership composition caused those outcomes.

Taken together, the findings suggest that rising participation is encouraging, but it should not be mistaken for closing the gap: recognition within teams, entry into patenting and access to research resources are distinct issues.[14]

Sources:

- [1] “Studies on the gender of inventors on patents show that gender imbalances persist, with substantial differences across countries and technology fields.” / “However, women's participation in patenting is rising.” / “For example, in the three years to 2022, the share of PCT applications from Australia with at least one woman inventor increased by three percentage points to 26% (see Figure 7.2).” / “At the same time, the share of unique women inventors on Australian PCT applications remained relatively constant.”
- [2] “For example, in the three years to 2022, the share of PCT applications from Australia with at least one woman inventor increased by three percentage points to 26% (see Figure 7.2).”
- [3] “At the same time, the share of unique women inventors on Australian PCT applications remained relatively constant.” / “In 2022, women constituted 14.6% of Australian inventors, the same level as in 2021.” / “Women account for 15% of unique inventors named on PCT applications from Australia.” / “This represents a participation rate 2 percentage points lower than the international average (see Figure 7.1).”
- [4] “Data on Australians' patenting activity suggests that growth in women's participation is occurring in mixed-gender teams.” / “That increase in participation is primarily due to growth in applications attributed to mixed teams, involving both men and women inventors.” / “The results could reflect change in the team composition of inventors or, alternatively, shifts in organisational practice with women inventors more likely to be recognised on patent applications for their contributions.”
- [5] “At the same time, the share of unique women inventors on Australian PCT applications remained relatively constant.” / “An alternative reading of these trends is that women inventors are filing patents more intensively without significant growth in the women inventor pool.”
- [6] “Research from the US shows that the gender gap is greatest in the first contact of inventors with the patent system.” / “Among previous patent inventors, there is only a 6% gap in the number of women and men inventors who patent again within five years 19 .”
- [7] “Research from the US shows that the gender gap is greatest in the first contact of inventors with the patent system.”
- [8] “Evidence shows there are no systematic productivity differences between women and men in creative and innovative endeavours 17 .”
- [9] “In 2022, women inventors were named on around half of PCT applications in Biotechnology (61%), Organic fine chemistry (59%), Pharmaceuticals (59%), Analysis of biological materials (56%) and Food chemistry (56%).”
- [10] “Other factors that may contribute to the gender patent gap include the nature of women's research 13 , under-crediting of women in science output 14 , and disparity in research funding 15 .”
- [11] “Women entrepreneurs, for example, reportedly receive less funding and on less favourable terms than men when it comes to follow-on R&D investment 16 .”
- [12] “However, gender diverse teams tend to produce more radical innovations and higher-impact scientific ideas 18 .”
- [13] “Among firms with a STEM workforce, the representation of women in leadership is associated with lower research intensity but greater efficiency in converting R&D investment into IP.”
- [14] “The results could reflect change in the team composition of inventors or, alternatively, shifts in organisational practice with women inventors more likely to be recognised on patent applications for their contributions.” / “An alternative reading of these trends is that women inventors are filing patents more intensively without significant growth in the women inventor pool.” / “Research from the US shows that the gender gap is greatest in the first contact of inventors with the patent system.” / “Other factors that may contribute to the gender patent gap include the nature of women's research 13 , under-crediting of women in science output 14 , and disparity in research funding 15 .”

*Follow-ups offered:* Why is the share of applications involving women different from the share of women inventors? · What did the research find about women in business leadership and innovation? · What evidence links funding barriers to the gender gap in patenting?

### Why did that happen? Explain it simply.

(A follow-up to: "How have patent applications in Australia changed over the last decade?")

**answer-v4** (complete, 8 claims)

**The recent decline mainly reflects fewer applications from overseas—especially the United States—not a broad retreat by Australian inventors.** In 2024, the fall was entirely attributable to overseas applicants, while Australian-resident applications rose slightly; the latest report says domestic patenting strengthened in 2025.[1][2]

### What has declined?

The figures here concern **standard patent applications filed in Australia**, including applications from overseas—not just inventions by Australians.[1]

- **In 2024, total filings fell by 3.3 per cent**, driven by fewer United States applications and reduced patenting across health technology fields.[3]
- **In 2025, total standard complete filings declined by less than 1 per cent**—so the latest result is closer to stability than a sharp downturn.[4]

### What explains it, in simple terms?

**1. Overseas applicants have a very large influence on the total.** Non-residents accounted for 91.5 per cent of standard patent filings in 2024, so their reduced filings outweighed the 0.9 per cent increase in Australian-resident applications, to 2,578.[1]

**2. United States filings have eased after their pandemic-era rise.** The 2025 report describes the 6.2 per cent fall in United States filings in 2024 as a correction following significant growth during the COVID-19 shock; United States filings then fell another 5.0 per cent in 2025.[5][6] In everyday terms, some of the recent decline represents an easing after an unusually strong period, rather than an entirely new downward trend.[5]

**3. Economic conditions and technology mix also matter.** The 2024 report linked the decline in 2023 to fewer United States filings, noting that United States firms’ patenting was highly sensitive to interest-rate shocks.[7] Health technology weakness continued to weigh on the 2024 total, although biotechnology bucked that pattern, with filings rising 4.7 per cent.[3] That means the decline was not uniform across technologies.[3]

**4. Australian applicants have followed a different path.** Domestic patenting strengthened in 2025, while China-origin applications increased by 13.4 per cent—further evidence that the overall total masks different movements underneath.[2][6]

### Why the longer trend looks uneven

Some earlier swings also reflected **when applicants filed**, rather than simply whether they were inventing: Australian-resident filings rose 24.8 per cent in 2021, then fell 16.8 per cent in 2022.[8] The report says the phase-out of innovation patents likely encouraged applicants to bring standard applications forward into 2021, with the following year’s fall representing a correction.[8]

**Taken together:** the evidence points to overseas filing decisions, a cooling after earlier growth, and changes in particular technology fields—not a single, across-the-board collapse in Australian inventive activity.[1][3][5][6] These are the reports’ explanations and interpretations; the 2026 report says several factors *likely* influenced country-level changes, including technological competition, patent portfolio rebalancing and policy developments, rather than identifying one proven cause.[6]

Sources:

- [1] “The decline in standard patent filings in 2024 was entirely attributed to reduced filings by non-residents (entities outside Australia). These account for 91.5% of annual standard patent filings in Australia.” / “In contrast, applications by Australian residents increased by 0.9%, to 2,578 in total”
- [2] “Resident patenting has strengthened, even as global portfolios are being rationalised”
- [3] “Overall filings fell by 3.3%, driven by reduced applications from the United States, and reduced patenting across health technology fields.” / “Biotechnology was the exception, with a 4.7% increase in filings, sourced from across geographic regions.”
- [4] “even as total standard complete filings declined by less than 1%.”
- [5] “In 2024, US filings fell for the second consecutive year, down by 6.2% from 2023 level. The decline represents a correction from significant growth during the COVID-19 shock.”
- [6] “US-origin filings declined in absolute terms (-5.0% from 2024 levels), continuing a longer-term easing in Australia.” / “China-origin filings increased markedly (+13.4%), reflecting ongoing growth in applied and industrial technologies and continued outward engagement by Chinese firms.” / “Diverse factors are likely to have shaped these movements, including technological competition, portfolio rebalancing, and policy developments in major overseas markets.”
- [7] “Overall patent filings fell by 2.4%, driven by a reduction in US filings, with US firms highly sensitive to rates shocks in their patenting activity.”
- [8] “Resident applications fell by 16.8% in 2022. However, this follows a 24.8% growth in resident filings in 2021” / “As a result, this policy change likely encouraged applicants to bring forward standard patent applications in 2021. The fall in resident applications in 2022 comprises a correction from the marked growth in 2021.”

*Follow-ups offered:* Which technology fields are growing despite the overall decline? · How do interest rates affect patenting, and how strong is the evidence? · What is driving the stronger patenting activity among Australian applicants?

**answer-v5** (complete, 8 claims)

**The simplest explanation is a gentle upward trend, interrupted by changes in filing timing and overseas demand—not steady growth every year.** Standard patent applications filed in Australia rose from 28,605 in 2015 to 30,348 in 2025, an increase of about 6% calculated from those totals. [1]

The reports point to several reasons for the fluctuations:

- **Law changes shifted when people filed.** Before the *Raising the Bar* reforms raised the requirements for patent grants in 2013, applicants rushed to file. Applications then dropped in 2014 before returning to a mild growth trend, including a 10% rebound in 2015. So the decade’s starting point was already affected by an unusual filing cycle. [2]
- **Some falls reflected changes in follow-on applications.** The small decline in 2019 was largely due to fewer “divisional” applications—applications containing subject matter from an earlier application. It was therefore not simply a fall in new, original filings. [3]
- **The pandemic period brought a peak, followed by an easing.** Applications fell by 2% in 2020, but then reached record levels in 2021 and 2022. The 2026 report describes the subsequent easing as a return towards more normal filing levels rather than a sustained contraction. [4]
- **Overseas applicants strongly influence the total.** They accounted for 90.7% of filings in 2025. That year, their applications fell by 1.3%, while Australian residents’ applications rose by 9.0%; together, these movements left total applications down just 0.5%. [5]

**The important caution:** applications are not a real-time measure of all innovation. For applicants using the Patent Cooperation Treaty route, there is an average 18-month gap between their first filing globally and filing in Australia, so annual figures can reflect earlier investment decisions. [6] And resident patenting reflects a relatively small group of research-intensive, technologically specialised firms—not business activity generally. [7]

Taken together, the evidence supports a picture of **modest long-term growth with timing effects, a pandemic-era peak and changing overseas filings**. It does not establish one single cause for the whole decade’s increase. [8]

Sources:

- [1] “The US, Japan, Germany and the UK filed 63 per cent of patents in Australia Patent applications: IP Australia received 28 605 standard patent applications in 2015, an increase of 10 per cent from 2014.” / “In 2025, Australia received 30,348 standard patent applications, marginally below 30,487 in 2024 (-0.5%) and down from 31,530 in 2023 (-3.8% over 2 years).”
- [2] “A surge in patenting in 2013 anticipated the implementation of the Raising the Bar legislative reforms announced in 2012, which raised the quality threshold for patent grants.3 Growth in applications prior to the reform was followed by a large decrease in applications in 2014, before returning to their overall mild growth trend until 2019.” / “The US, Japan, Germany and the UK filed 63 per cent of patents in Australia Patent applications: IP Australia received 28 605 standard patent applications in 2015, an increase of 10 per cent from 2014.”
- [3] “Standard patent applications: In 2019, a total of 29 758 applications for standard patents were filed, a 0.7 per cent decrease from their level in 2018 (Figure 1).” / “The fall can be largely attributed to a decrease in divisional applications-patent applications which contain subject matter from previously filed applications.” / “For direct filings, divisional applications fell 2.9 per cent in 2019, while original applications fell 1.2 per cent.”
- [4] “In 2020, IP Australia received 29 293 standard patent applications, including divisional applications – a 2 per cent decrease compared to 2019 (Figure P1), but still higher than the 10-year annual average of 28 308 applications.” / “In Australia, the COVID-19 shock saw an increase in the volume of patent filings in Australia to record levels in 2021 and 2022 (see Figure 1.1).” / “After a clear post-pandemic peak early in the decade, recent years point to normalisation rather than contraction.”
- [5] “As a result, the nonresident share eased slightly to 90.7%.” / “Non-resident filings declined modestly in 2025, from 27,909 in 2024 to 27,538 (-1.3%).” / “Australian applicants filed 2,810 standard complete applications in 2025, up from 2,578 in 2024 - an increase of 9.0%.” / “In 2025, Australia received 30,348 standard patent applications, marginally below 30,487 in 2024 (-0.5%) and down from 31,530 in 2023 (-3.8% over 2 years).”
- [6] “On average, for applicants who file in Australia through the PCT system, there is an 18-month delay between when they first file a patent application globally and when they file that patent in Australia (it enters Australian 'national phase').” / “As such, PCT applications in 2024 may reflect innovation investments made over 2023 or earlier.”
- [7] “Unlike trade marks or designs, patenting in Australia is not a broad barometer of business dynamism and commercial activity.” / “Instead, resident patenting reflects activity by a relatively small subset of firms engaged in R&D-intensive and technologically specialised innovation.”
- [8] “A surge in patenting in 2013 anticipated the implementation of the Raising the Bar legislative reforms announced in 2012, which raised the quality threshold for patent grants.3 Growth in applications prior to the reform was followed by a large decrease in applications in 2014, before returning to their overall mild growth trend until 2019.” / “In Australia, the COVID-19 shock saw an increase in the volume of patent filings in Australia to record levels in 2021 and 2022 (see Figure 1.1).” / “After a clear post-pandemic peak early in the decade, recent years point to normalisation rather than contraction.” / “Non-resident filings declined modestly in 2025, from 27,909 in 2024 to 27,538 (-1.3%).”

*Follow-ups offered:* Why do overseas applicants account for so many Australian patent filings? · What does the recent rise in Australian resident applications tell us? · How do patent applications differ from patents granted?
