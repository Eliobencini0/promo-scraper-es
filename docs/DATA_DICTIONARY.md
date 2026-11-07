# Data dictionary

One row per promotion. Column order is fixed in `config.CSV_HEADER`; values are built in `extractor.build_row()`. "Flag" means the field name is added to `_confidence` when the value is empty.

| Column | Meaning | Where it comes from | If it cannot be found |
|---|---|---|---|
| `cashback_id` | Stable id of the promotion, derived from the article URL. Deduplication key | `extractor.url_to_cashback_id` | never empty |
| `title` | Promotion title | article page | |
| `brand` | Brand running the promotion | article page (heuristic on the heading) | flagged by the article parser when unsure |
| `description` | Short description | article page | |
| `where_to_buy` | Where the promotion is valid (territory, store type) | legal terms, section "territorial"; else a regular expression over the legal text; else patterns on the brand page | empty, flag |
| `validity` | Normalised end date, only when the parser is confident | `validity.py` | empty |
| `reimbursement` | The prize or refund | legal terms, section "premio / regalo / reembolso / cashback" (first paragraph, 600 characters); else regular expressions on the brand page | empty, flag |
| `claim_method` | How to take part | legal terms, section "mecánica / participación" (700 characters); else patterns on the brand page | empty, flag |
| `physical_stores` | Mentions of physical stores or points of sale | regular expression over legal and brand text | empty, flag |
| `channel` | The participation link ("Participar") | article page | |
| `image` | Main image | brand landing page; rejected if it comes from the source blog, social widgets or trackers | empty, flag |
| `[extra] categoria` | Category slug where the article was found; `sitemap` if found only in the sitemap; `manual` for `--url` | discovery | |
| `[extra] mecanica_full` | Structured summary built from the brand's legal terms (Premio, Mecánica, Duración, Ámbito, Requisitos, Entrega, Exclusiones, each one paragraph); fallback: snippets from the brand page | `extractor._synthesize_mecanica` | empty, flag |
| `[extra] passo_1_acquisto` … `passo_5_erogazione` | The five steps: purchase, documents, verification, registration, payout or prize delivery | legal sections by keyword; else sub-steps split out of the "mecánica" section; else older regular expressions | empty, flag each |
| `[extra] canali_esclusi` | Who or what is excluded | legal terms, exclusions section; else the phrase "quedan excluidos / no podrán participar" | empty, flag |
| `[extra] form_registrazione_url` | Registration form link | same as `channel` | |
| `[extra] bases_legales_url` | Link to the legal terms | article page | |
| `[extra] contatto_promo` | Contact for the promotion: first email, else first Spanish phone number, in the legal text | | empty, flag |
| `[extra] conviene_se` | "Worth it if…" | **always empty**: editorial | always flagged |
| `[extra] attenzione_se` | "Watch out if…" | **always empty**: editorial | always flagged |
| `_source_url` | The article this row came from | | |
| `_scraped_at` | UTC timestamp of extraction | | |
| `_confidence` | Comma-separated, sorted list of fields that are empty or low confidence; always contains the two editorial columns | | |
| `validity_end_date` | End date as `YYYY-MM-DD` | `validity.py` | empty |

Reading rule: an empty cell means "not found with a rule the code can point to", never "does not exist".
