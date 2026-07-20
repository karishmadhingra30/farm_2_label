/* =========================================================================
   table.js — the full dataset, searchable and sortable.

   Why this view exists
   --------------------
   The tree and the map are arguments. This is the evidence. Every row, every
   source link, every date, in a form a reader can check line by line and a
   sceptic can pick holes in. A data project that shows only its charts is
   asking to be believed; one that shows its table is asking to be checked.

   It also does accessibility work for the charts above it. Three of the seven
   owner-type colours fall below the contrast ratio that would let colour
   carry meaning on its own, and this table is the text version that makes
   that acceptable: nothing on the page is knowable only by hue.

   No framework and no virtual DOM. Around fifty rows rebuild in well under a
   frame, so re-rendering the whole tbody on every keystroke is simpler and
   fast enough.

   This file exposes `window.BrandTable.init(options)`.
   ========================================================================= */

window.BrandTable = (function () {
  "use strict";

  /* The column definitions drive both the header and the body, so a column
     cannot exist in one and not the other.

     key      identifies the column for sorting
     label    the heading text
     sortable whether the heading is a button
     value    the string a search matches and a sort compares
     cell     the HTML for one body cell */
  function buildColumns(helpers) {
    var esc = helpers.escape;

    /* A place, written as "City, ST", or an em-free placeholder when the row
       has a declared gap. */
    function place(obj) {
      if (!obj || !obj.city) return "not confirmed";
      return obj.city + (obj.state ? ", " + obj.state : "");
    }

    return [
      {
        key: "brand",
        label: "Brand",
        sortable: true,
        value: function (row) { return row.brand; },
        cell: function (row) {
          /* The coloured dot ties this row to its colour in the tree and on
             the map. The owner type is also written out in its own column,
             so the dot adds recognition rather than carrying meaning. */
          /* Two different badges, because two different things can be
             short. "1 source" is the serious one and says the ownership
             claim is not double-sourced. "origin?" is the narrow one and
             says only that the brand's self-claimed home town is not cited
             to the brand's own page. Both carry a word, never colour
             alone. */
          var badges = "";
          if (row.unverified) {
            badges += ' <span class="flag" title="Ownership is not backed by ' +
              'two independently read sources">1 source</span>';
          }
          if (row.origin_unconfirmed) {
            badges += ' <span class="flag flag--minor" title="Origin is not ' +
              'cited to the brand\'s own page">origin?</span>';
          }
          return '<td class="cell-brand">' +
            '<span class="dot" style="background:' +
            helpers.colorFor(row.parent_type) + '"></span>' +
            esc(row.brand) + badges +
            "</td>";
        }
      },
      {
        key: "category",
        label: "Category",
        sortable: true,
        value: function (row) { return row.category; },
        cell: function (row) {
          return "<td>" + '<span class="pill">' + esc(row.category) + "</span></td>";
        }
      },
      {
        key: "signal",
        label: "Why it qualified",
        sortable: true,
        value: function (row) {
          return helpers.signalLabel(row.qualifying_signal) + " " + row.signal_evidence;
        },
        cell: function (row) {
          /* The full quote goes on the title attribute so nothing is lost
             when the visible text is clamped. */
          return '<td class="cell-evidence" title="' +
            esc(row.signal_evidence) + '">' +
            '<span class="pill">' + esc(helpers.signalLabel(row.qualifying_signal)) +
            "</span>" +
            '<div class="cell-evidence__text">' + esc(row.signal_evidence) +
            "</div></td>";
        }
      },
      {
        key: "origin",
        label: "Says it is from",
        sortable: true,
        value: function (row) { return place(row.brand_origin); },
        cell: function (row) {
          var text = esc(place(row.brand_origin));
          /* The origin is the brand's own claim, so it links to the brand's
             own page rather than to anything we wrote. */
          if (row.brand_origin.source) {
            return "<td>" + '<a href="' + esc(row.brand_origin.source) +
              '" rel="noopener nofollow">' + text + "</a></td>";
          }
          return '<td class="cell-date">' + text + "</td>";
        }
      },
      {
        key: "direct_owner",
        label: "Direct owner",
        sortable: true,
        value: function (row) { return row.direct_owner; },
        cell: function (row) { return "<td>" + esc(row.direct_owner) + "</td>"; }
      },
      {
        key: "ultimate_parent",
        label: "Ultimate parent",
        sortable: true,
        value: function (row) { return row.ultimate_parent; },
        cell: function (row) {
          return '<td class="cell-owner">' + esc(row.ultimate_parent) + "</td>";
        }
      },
      {
        key: "parent_type",
        label: "Owner type",
        sortable: true,
        value: function (row) { return helpers.labelFor(row.parent_type); },
        cell: function (row) {
          return "<td>" + esc(helpers.labelFor(row.parent_type)) + "</td>";
        }
      },
      {
        key: "parent_hq",
        label: "Owner HQ",
        sortable: true,
        value: function (row) { return place(row.parent_hq); },
        cell: function (row) { return "<td>" + esc(place(row.parent_hq)) + "</td>"; }
      },
      {
        key: "sources",
        label: "Sources",
        sortable: false,
        value: function (row) { return row.sources.join(" "); },
        cell: function (row) {
          var links = row.sources.map(function (url, index) {
            /* The link text is the source's domain, so a reader can see at a
               glance whether a claim rests on the company's own page or on
               someone else's report. */
            var host = url;
            try {
              host = new URL(url).hostname.replace(/^www\./, "");
            } catch (error) {
              host = "source " + (index + 1);
            }
            return '<a href="' + esc(url) + '" rel="noopener nofollow">' +
              esc(host) + "</a>";
          }).join("");
          return '<td><div class="sources">' + links + "</div></td>";
        }
      },
      {
        key: "verified_on",
        label: "Checked",
        sortable: true,
        value: function (row) { return row.verified_on; },
        cell: function (row) {
          return '<td class="cell-date">' +
            esc(helpers.formatDate(row.verified_on)) + "</td>";
        }
      }
    ];
  }

  function init(options) {
    var head = options.head;
    var body = options.body;
    var status = options.status;
    var search = options.search;
    var data = options.data;
    var helpers = options.helpers;
    var onSelect = options.onSelect;

    var columns = buildColumns(helpers);
    var sortKey = "brand";
    var sortAscending = true;
    var query = "";
    var selectedBrand = null;

    /* -------------------------------------------------------------------
       Header
       ------------------------------------------------------------------- */

    /**
     * Draw the header row, with a sort button in each sortable column.
     *
     * Why a button inside the th rather than a click handler on the th
     * itself: a button is reachable by Tab and activates with Enter or
     * Space for free. A clickable th is invisible to a keyboard.
     */
    function renderHead() {
      head.innerHTML = columns.map(function (column) {
        if (!column.sortable) {
          return "<th scope=\"col\"><button type=\"button\" disabled " +
            "style=\"cursor:default\">" + helpers.escape(column.label) +
            "</button></th>";
        }

        var isSorted = column.key === sortKey;
        /* aria-sort is how a screen reader announces the current sort. It
           is only present on the one sorted column, per the spec. */
        var ariaSort = isSorted
          ? ' aria-sort="' + (sortAscending ? "ascending" : "descending") + '"'
          : "";
        var arrow = isSorted ? (sortAscending ? "▲" : "▼") : "↕";

        return '<th scope="col"' + ariaSort + ">" +
          '<button type="button" data-sort="' + column.key + '">' +
          helpers.escape(column.label) +
          '<span class="sort-arrow" aria-hidden="true">' + arrow + "</span>" +
          "</button></th>";
      }).join("");

      Array.prototype.forEach.call(
        head.querySelectorAll("button[data-sort]"),
        function (button) {
          button.addEventListener("click", function () {
            var key = button.getAttribute("data-sort");
            /* Clicking the sorted column reverses it; clicking a new one
               starts that column ascending. */
            if (key === sortKey) sortAscending = !sortAscending;
            else { sortKey = key; sortAscending = true; }
            renderHead();
            renderBody();
          });
        }
      );
    }

    /* -------------------------------------------------------------------
       Body
       ------------------------------------------------------------------- */

    function columnByKey(key) {
      for (var i = 0; i < columns.length; i += 1) {
        if (columns[i].key === key) return columns[i];
      }
      return columns[0];
    }

    /**
     * Apply the search box to the brand list.
     *
     * The search looks at every column's value plus the row's notes, so
     * typing "employee" finds the employee-owned rows and typing "Vermont"
     * finds both a brand from Vermont and an owner headquartered there.
     */
    function matchingRows() {
      if (!query) return data.brands.slice();

      var needle = query.toLowerCase();
      return data.brands.filter(function (row) {
        var haystack = columns.map(function (column) {
          return column.value(row);
        }).join(" ") + " " + row.notes;
        return haystack.toLowerCase().indexOf(needle) !== -1;
      });
    }

    function sortRows(rows) {
      var column = columnByKey(sortKey);
      return rows.sort(function (a, b) {
        var left = String(column.value(a) || "");
        var right = String(column.value(b) || "");
        /* localeCompare with numeric:true means "Brand 2" sorts before
           "Brand 10", which plain string comparison gets wrong. */
        var result = left.localeCompare(right, undefined, {
          numeric: true,
          sensitivity: "base"
        });
        return sortAscending ? result : -result;
      });
    }

    function renderBody() {
      var rows = sortRows(matchingRows());

      if (!rows.length) {
        body.innerHTML = "";
        status.textContent = query
          ? 'No brands match "' + query + '".'
          : "No brands in the dataset yet.";
        return;
      }

      body.innerHTML = rows.map(function (row) {
        var classes = row.brand === selectedBrand ? ' class="is-selected"' : "";
        return "<tr" + classes + ' data-brand="' + helpers.escape(row.brand) + '">' +
          columns.map(function (column) { return column.cell(row); }).join("") +
          "</tr>";
      }).join("");

      /* Clicking a row selects that brand, which highlights it in the tree
         and on the map. The handler sits on the tbody rather than on every
         row, so there is one listener regardless of row count. */
      var s = data.summary;
      status.textContent = query
        ? "Showing " + rows.length + " of " + data.brands.length + " brands."
        : "Showing all " + rows.length + " brands. " +
          s.unverified_count + " without two independently read ownership " +
          "sources, " + s.origin_unconfirmed_count + " whose claimed origin " +
          "is not cited to the brand's own page.";
    }

    /* One delegated listener for the whole table body. */
    body.addEventListener("click", function (event) {
      /* A click on a source link should follow the link, not select a row. */
      if (event.target.closest("a")) return;
      var row = event.target.closest("tr[data-brand]");
      if (row) onSelect(row.getAttribute("data-brand"));
    });

    /* -------------------------------------------------------------------
       Search
       ------------------------------------------------------------------- */

    search.addEventListener("input", function () {
      query = search.value.trim();
      renderBody();
    });

    /* -------------------------------------------------------------------
       Start
       ------------------------------------------------------------------- */

    renderHead();
    renderBody();

    return {
      onSelect: function (brandName) {
        selectedBrand = brandName;
        renderBody();

        /* Bring the selected row into view, so selecting a brand in the tree
           does not leave its evidence somewhere off screen. `block: nearest`
           scrolls the minimum distance rather than yanking the row to the
           middle of the window. */
        if (brandName) {
          var row = body.querySelector(
            'tr[data-brand="' + String(brandName).replace(/"/g, '\\"') + '"]'
          );
          if (row && row.scrollIntoView) {
            row.scrollIntoView({ block: "nearest", behavior: "smooth" });
          }
        }
      }
    };
  }

  return { init: init };
})();
