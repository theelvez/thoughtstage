import "@testing-library/jest-dom/vitest";

HTMLElement.prototype.scrollIntoView = function scrollIntoView() {
  return undefined;
};
