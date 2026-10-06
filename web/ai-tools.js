/* AI preview variants and persistent review marks; no changes to caption text. */
(function (root) {
  function reviewReasons(...rows) {
    return [...new Set(rows.flatMap(row => row.reviewReasons || []))];
  }

  function cloneRow(row) {
    return {...row, preservedCase: new Set(row.preservedCase), reviewReasons: reviewReasons(row)};
  }

  function variant(data, kind) {
    const groups = kind === 'groups';
    const lines = groups ? data.groups : data.lines;
    const ends = groups ? data.group_ends : data.ends;
    const notes = lines.map(() => []);
    lines.forEach((text, index) => {
      if (Array.from(text).length > data.max_chars) notes[index].push('превышение лимита символов');
    });
    for (const warning of (groups ? data.group_quality_warnings : data.quality_warnings) || []) {
      if (notes[warning.index - 1]) notes[warning.index - 1].push(warning.reason);
    }
    return {lines, ends, notes: notes.map(reasons => [...new Set(reasons)])};
  }

  function applyVariant(rows, proposal) {
    const selected = new Set();
    const previousMarks = [];
    let offset = 0;
    for (const row of rows) {
      const end = offset + (row.text.match(/\S+/gu) || []).length;
      row.preservedCase.forEach(index => selected.add(offset + index));
      if (row.reviewReasons?.length) previousMarks.push({start: offset, end, reasons: row.reviewReasons});
      offset = end;
    }
    let first = 0;
    return proposal.lines.map((text, index) => {
      const end = proposal.ends[index];
      const preservedCase = new Set([...selected].filter(n => n >= first && n < end).map(n => n - first));
      const inherited = previousMarks.filter(mark => mark.start < end && mark.end > first).flatMap(mark => mark.reasons);
      const reasons = [...new Set([...inherited, ...proposal.notes[index]])];
      first = end;
      return {text, preservedCase, reviewReasons: reasons};
    });
  }

  const api = {reviewReasons, cloneRow, variant, applyVariant};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.SubtitleAI = api;
})(typeof window !== 'undefined' ? window : globalThis);
