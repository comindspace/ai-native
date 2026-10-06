# Business economics dashboard (first iteration)

Open `/admin/metrics` with `access:admin`, `tracker:read`, and `bitrix24:read`. The
default section is Business. The Gateway administrator selects a Tracker project,
links it to one Bitrix24 deal, and confirms that the CRM amount and currency match
the signed contract. The confirmation is invalidated if either value changes in CRM.
The link and confirmation are audited in Gateway Postgres; no CRM token is stored.

Tracker issue worklogs are read for the whole project. The cost estimate is the sum
of each author's hours times their configured hourly planning rate. A Tracker day
is interpreted as eight hours and a week as forty hours. Author IDs come from
`createdBy`, which assumes employees enter their own time. The roster in Yonote is
not used to infer Tracker identities or salaries: it has no reliable account-to-role
mapping. Authors who appear in worklogs are shown in the dashboard so an admin can
review their estimates. Until reviewed, each uses a **market proxy of 1,800 RUB/h**:
the [Habr Career 2026 median](https://habr.com/ru/specials/1060148/) of 191,000
RUB/month divided by 160 hours, multiplied by an *assumed* 1.5 cost factor and
rounded. Neither that factor nor the rate is a company's actual payroll cost. A
new rate applies to the entire worklog history in this first iteration.

The "balance after logged labor" is `confirmed CRM amount - estimated labor cost`.
It is **not** recognized revenue, profit, cash flow, or final project margin. Taxes,
subcontractors, cloud/model spending, sales costs, and remaining work are excluded.
The value is hidden when the contract is unconfirmed, CRM currency is not RUB, the
Tracker sample is capped/incomplete, a duration cannot be parsed, or an author ID
is missing, or no worklogs exist. Portfolio amounts are grouped by currency and only confirmed deals are
included; limited or failed CRM reads are labelled as partial. The current link
model supports one deal per Tracker project.

To make the dashboard decision-grade, the next data sources are: approved internal
cost rates with effective dates, contract amendments/multiple deals per project,
non-labor expenses, payment/recognition status, and an explicit remaining-effort
estimate. Do not turn the interim balance into a profitability KPI before then.
