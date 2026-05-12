# aihw-mcp — demo prompts

Six copy-paste prompts that demonstrate distinct sellable angles for the
aihw-mcp server. Each resolves to one or two `get_data` / `top_n` /
`describe_dataset` calls. Paste into Claude Desktop (or Cursor) with the
aihw-mcp MCP installed.

---

## 1. Public-health research — long-term cause-of-death trends

> "Using GRIM_DEATHS, get me the deaths and age-standardised rate per 100,000 for 'Diabetes' for Persons (both sexes combined) for every available year. Plot the trajectory and call out the inflection points."

Resolves to one `get_data("GRIM_DEATHS", filters={"cause_of_death": "Diabetes", "sex": "Persons", "age_group": "Total"})` call.

---

## 2. Health-tech — regional mortality hotspots

> "From MORT_GEOGRAPHY, give me the 10 Statistical Area Level 3 (SA3) regions with the highest age-standardised mortality rate for Persons in the most recent year on file. For each, also include the rate ratio (vs national) and the population."

Resolves to one `top_n("MORT_GEOGRAPHY", "age_standardised_rate_per_100000", n=10, filters={"category": "Statistical Area Level 3 (SA3)", "SEX": "Persons"})` call.

---

## 3. Oncology — cancer trends by age band

> "For breast cancer in CANCER_INCIDENCE_MORTALITY, give me the incidence counts for Females in the 50–54 age band (`age_50_to_54`) for every year. Then do the same for mortality. I want to compare the two series."

Resolves to two `get_data` calls — one with `type: "Incidence"` and one with `type: "Mortality"`, both filtered to `cancer_type: "Breast cancer", sex: "Female"`.

---

## 4. Health-policy — public hospital spend by state

> "From HEALTH_EXPENDITURE, what was the real spend on 'Public hospitals' in NSW in 2022-23, broken down by broad source (Government vs Non-government) and detailed source? Then compare against VIC for the same year."

Resolves to two `get_data` calls with `area_of_expenditure: "Public hospitals"` and the two states.

---

## 5. Criminal-justice tech — youth detention disparity

> "Using YOUTH_JUSTICE_DETENTION, compare the average nightly youth-detention population in NSW vs Vic in 'Jun qtr 2017'. Show both Indigenous and Total. Quantify the over-representation."

Resolves to one `get_data("YOUTH_JUSTICE_DETENTION", filters={"state": ["NSW", "Vic"], "quarter": "Jun qtr 2017", "legal_status": "Total", "sex": "Total"})` call.

---

## 6. Hospital-tech / market intel — peer group rollup

> "From PUBLIC_HOSPITALS, list every 'Principal referral' hospital with its state and Local Hospital Network. Then count how many there are per state."

Resolves to one `get_data("PUBLIC_HOSPITALS", filters={"peer_group_name": "Principal referral"})` call plus client-side grouping (Claude can do this from the records array).
