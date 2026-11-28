(function (root) {
  "use strict";

  function closeExpired(row, now) {
    if (!row[8] || !Number.isFinite(row[15]) || now < row[15]) return row;
    const closed = row.slice();
    closed[7] = "auction_closed";
    closed[8] = 0;
    return closed;
  }

  root.LandosaurAvailability = { closeExpired };
})(globalThis);
