// Registers @testing-library/jest-dom matchers (toBeInTheDocument, etc.) for
// component tests. Safe to load for node-env tests too — it only registers
// matchers; the DOM-dependent ones are used solely by jsdom-env test files.
import "@testing-library/jest-dom/vitest";
