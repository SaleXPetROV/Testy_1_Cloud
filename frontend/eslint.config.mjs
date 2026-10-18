// Minimal ESLint v9 flat config so the lint engine can parse the CRA codebase
// (JSX) without an engine error. Dev-time linting is handled by react-scripts;
// this only registers the plugins referenced by inline eslint-disable comments
// (react, react-hooks) so a bare `eslint` run does not fail on unknown rules.
import react from "eslint-plugin-react";
import reactHooks from "eslint-plugin-react-hooks";

export default [
  {
    ignores: ["build/**", "node_modules/**", "public/**", "plugins/**"],
  },
  {
    files: ["**/*.{js,jsx}"],
    plugins: {
      react,
      "react-hooks": reactHooks,
    },
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      parserOptions: {
        ecmaFeatures: { jsx: true },
      },
    },
    linterOptions: {
      reportUnusedDisableDirectives: false,
    },
    rules: {
      "react-hooks/exhaustive-deps": "off",
      "react-hooks/rules-of-hooks": "off",
    },
  },
];
