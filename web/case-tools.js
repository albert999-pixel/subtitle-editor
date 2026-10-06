/* Pure text operations shared by the editor and regression checks. */
(function (root) {
  function lowercaseExcept(text, protectedWords) {
    let index = 0;
    return text.replace(/\S+/gu, word => protectedWords.has(index++) ? word : word.toLowerCase());
  }

  function remapSelection(before, after, selected) {
    const oldWords = before.match(/\S+/gu) || [];
    const newWords = after.match(/\S+/gu) || [];
    // Input edits replace one contiguous span: preserve unchanged prefix/suffix.
    let prefix = 0;
    while (prefix < Math.min(oldWords.length, newWords.length) && oldWords[prefix] === newWords[prefix]) prefix++;
    let suffix = 0;
    while (suffix < Math.min(oldWords.length, newWords.length) - prefix &&
      oldWords[oldWords.length - 1 - suffix] === newWords[newWords.length - 1 - suffix]) suffix++;
    const result = new Set();
    selected.forEach(index => {
      if (index < prefix) result.add(index);
      else if (index >= oldWords.length - suffix) result.add(index + newWords.length - oldWords.length);
      else if (oldWords.length === newWords.length) result.add(index);
    });
    return result;
  }

  const api = {lowercaseExcept, remapSelection};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.SubtitleCase = api;
})(typeof window !== 'undefined' ? window : globalThis);
