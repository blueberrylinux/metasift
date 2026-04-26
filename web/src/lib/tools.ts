/**
 * Client-side catalog of Stew's local tools — names mirror `ALL_TOOLS` in
 * `app/engines/tools.py` (26 entries). Used by the Composer's ⌘K/Ctrl+K
 * palette to give users a discovery path into Stew's capabilities.
 *
 * `prompt` is the natural-language question inserted into the composer on
 * click. Keep it phrased as a question so LangChain's tool router picks
 * the intended tool. Where a tool needs an FQN or arg, the prompt leaves
 * a `{placeholder}` for the user to fill in before sending.
 *
 * Tool coverage here must stay in sync with `ALL_TOOLS`. When you add a
 * @tool in the backend, append a row here too.
 */

export type ToolCategory =
  | 'Discovery'
  | 'Analysis'
  | 'Cleaning'
  | 'Stewardship'
  | 'DQ · risk';

export interface StewTool {
  name: string;
  category: ToolCategory;
  description: string;
  prompt: string;
}

export const STEW_TOOLS: StewTool[] = [
  // Discovery
  {
    name: 'list_services',
    category: 'Discovery',
    description: 'Data sources connected to OpenMetadata (database / dashboard / messaging / pipeline).',
    prompt: 'Which data sources are connected to OpenMetadata?',
  },
  {
    name: 'list_schemas',
    category: 'Discovery',
    description: 'Every database + schema in the catalog with table counts.',
    prompt: 'List every schema in the catalog.',
  },
  {
    name: 'list_tables',
    category: 'Discovery',
    description: 'Tables in the catalog, optionally filtered by schema.',
    prompt: 'List every table in the sales schema.',
  },
  {
    name: 'about_metasift',
    category: 'Discovery',
    description: 'Project overview — composite score, engines, differentiators.',
    prompt: 'What is MetaSift and how does the composite score work?',
  },
  {
    name: 'run_sql',
    category: 'Discovery',
    description: 'Ad-hoc read-only SQL against the DuckDB metadata store.',
    prompt: 'Run this SQL: SELECT fullyQualifiedName FROM om_tables LIMIT 10',
  },

  // Analysis
  {
    name: 'composite_score',
    category: 'Analysis',
    description: 'Headline metric — weighted coverage, accuracy, consistency, quality.',
    prompt: "What's my composite score?",
  },
  {
    name: 'documentation_coverage',
    category: 'Analysis',
    description: 'Percent of tables documented, per schema.',
    prompt: 'How is documentation coverage distributed across schemas?',
  },
  {
    name: 'ownership_report',
    category: 'Analysis',
    description: 'Per-team scorecard + orphan tables.',
    prompt: 'Who owns what? Give me the stewardship scorecard.',
  },
  {
    name: 'impact_check',
    category: 'Analysis',
    description: 'Blast radius for a table — direct + transitive downstream, PII-weighted.',
    prompt: "What's the blast radius of {fullyQualifiedName}?",
  },
  {
    name: 'impact_catalog',
    category: 'Analysis',
    description: 'Catalog-wide top-N tables ranked by blast radius / impact score.',
    prompt: 'Show me the top 10 tables by blast radius.',
  },
  {
    name: 'pii_propagation',
    category: 'Analysis',
    description: 'Where does PII reach via lineage — origins, tainted downstream, edges.',
    prompt: 'Where does PII propagate across the catalog?',
  },

  // Cleaning
  {
    name: 'check_description_staleness',
    category: 'Cleaning',
    description: 'LLM-compare a table description against its actual columns.',
    prompt: 'Is the description of {fullyQualifiedName} still accurate?',
  },
  {
    name: 'find_tag_conflicts',
    category: 'Cleaning',
    description: 'Column names tagged inconsistently across tables.',
    prompt: 'Find tag conflicts across the catalog.',
  },
  {
    name: 'score_descriptions',
    category: 'Cleaning',
    description: 'Rate table descriptions 1-5 on specificity + accuracy.',
    prompt: 'Score the quality of the first 10 documented tables.',
  },
  {
    name: 'find_naming_inconsistencies',
    category: 'Cleaning',
    description: 'Fuzzy-matched column-name drift (cust_id vs customer_id).',
    prompt: 'Find naming inconsistencies across columns.',
  },

  // Stewardship
  {
    name: 'generate_description_for',
    category: 'Stewardship',
    description: 'Draft a description for an undocumented table.',
    prompt: 'Draft a description for {fullyQualifiedName}.',
  },
  {
    name: 'auto_document_schema',
    category: 'Stewardship',
    description: 'Bulk-draft descriptions for every undocumented table in a schema.',
    prompt: 'Auto-document the sales schema.',
  },
  {
    name: 'apply_description',
    category: 'Stewardship',
    description: 'Push an approved description back to OpenMetadata (after review).',
    prompt: 'Apply the approved description for {fullyQualifiedName}.',
  },
  {
    name: 'scan_pii',
    category: 'Stewardship',
    description: 'Detect + classify potential PII columns (heuristic + optional LLM).',
    prompt: 'Scan the catalog for PII columns.',
  },
  {
    name: 'find_pii_gaps',
    category: 'Stewardship',
    description: 'Columns that look like PII but have no sensitivity tag.',
    prompt: 'Which columns look like PII but are untagged?',
  },
  {
    name: 'apply_pii_tag',
    category: 'Stewardship',
    description: 'Tag a column as PII.Sensitive / PII.NonSensitive / PII.None.',
    prompt: 'Tag the {column} column in {fullyQualifiedName} as PII.Sensitive.',
  },

  // DQ · risk
  {
    name: 'dq_failures_summary',
    category: 'DQ · risk',
    description: 'Every failing DQ test with a plain-English explanation.',
    prompt: 'Summarize failing DQ tests across the catalog.',
  },
  {
    name: 'dq_explain',
    category: 'DQ · risk',
    description: 'Explain one failing DQ test — likely cause + next step.',
    prompt: 'Explain the failing DQ tests on {fullyQualifiedName}.',
  },
  {
    name: 'recommend_dq_tests',
    category: 'DQ · risk',
    description: 'Severity-ranked DQ tests that should exist on a table but don\'t.',
    prompt: 'Recommend DQ tests for {fullyQualifiedName}.',
  },
  {
    name: 'find_dq_gaps',
    category: 'DQ · risk',
    description: 'Catalog-wide DQ gaps grouped by severity.',
    prompt: 'Show me catalog-wide DQ test gaps by severity.',
  },
  {
    name: 'dq_impact',
    category: 'DQ · risk',
    description: 'Downstream risk from a table\'s failing DQ tests (PII-amplified).',
    prompt: 'What is the downstream DQ risk of {fullyQualifiedName}?',
  },
  {
    name: 'dq_risk_catalog',
    category: 'DQ · risk',
    description: 'Rank the whole catalog by DQ risk score.',
    prompt: 'Rank the catalog by DQ risk.',
  },
];

export const TOOL_CATEGORIES: ToolCategory[] = [
  'Discovery',
  'Analysis',
  'Cleaning',
  'Stewardship',
  'DQ · risk',
];
