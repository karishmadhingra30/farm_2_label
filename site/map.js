/* =========================================================================
   map.js — the geographic view: claimed origin against owner headquarters.

   Why this view exists
   --------------------
   The tree answers "who owns this". This answers a different question: how
   far is the story from the structure. A brand whose packaging talks about a
   valley in Oregon, owned by a company run from an office in Illinois, draws
   a line across most of a continent. A brand still run from the mill it is
   named after draws no line at all, because both points sit on top of each
   other. Read together, the absence of a line is as informative as a long
   one.

   What Leaflet is
   ---------------
   Leaflet is the map library. It handles the parts that are genuinely hard:
   fetching map tiles as you pan, converting latitude and longitude into
   pixel positions at the current zoom, and keeping the overlays lined up
   with the tiles underneath. It is loaded from a CDN in index.html.

   The tiles come from CARTO's Positron style, which is free to use with
   attribution. It is a deliberately pale, low-contrast basemap, so the data
   drawn on top is the thing you see.

   This file exposes `window.OriginMap.init(options)`.
   ========================================================================= */

window.OriginMap = (function () {
  "use strict";

  /* Marker sizes, in pixels of radius. Both are comfortably above the 8px
     minimum that makes a target hittable with a thumb. */
  var ORIGIN_RADIUS = 5;
  var HQ_RADIUS_MIN = 7;
  var HQ_RADIUS_MAX = 16;

  /* The starting view: the continental United States, which is where almost
     every brand in this dataset sits. The map fits itself to the real data
     after drawing, so this is only the frame before that happens. */
  var INITIAL_CENTER = [39.5, -96.5];
  var INITIAL_ZOOM = 4;

  /**
   * Turn a CSS custom property reference into a real colour string.
   *
   * Why it exists: the rest of this project hands SVG `var(--type-x)` and
   * lets the browser resolve it, which is what makes dark mode free. Leaflet
   * cannot do that, because it writes colours into SVG presentation
   * attributes, and those do not understand `var()`. So the variable has to
   * be read off the document and passed as a literal colour.
   *
   * The consequence is that the map has to be redrawn when the colour scheme
   * changes. The listener at the bottom of init() does that.
   */
  function resolveColor(cssValue) {
    var match = /^var\((--[^)]+)\)$/.exec(String(cssValue).trim());
    if (!match) return cssValue;
    var resolved = getComputedStyle(document.documentElement)
      .getPropertyValue(match[1])
      .trim();
    return resolved || "#888888";
  }

  function init(options) {
    var container = options.container;
    var data = options.data;
    var helpers = options.helpers;
    var onSelect = options.onSelect;
    var buttons = Array.prototype.slice.call(options.buttons || []);

    var map = null;
    var overlay = null;        // one Leaflet layer group holding everything drawn
    var filter = "all";
    var selectedBrand = null;

    /* Keeps the drawn objects for one brand, so a selection can restyle them
       without searching the layer tree. */
    var drawnByBrand = {};

    /* ---------------------------------------------------------------------
       Which brands to show
       --------------------------------------------------------------------- */

    /**
     * Apply the current toggle to the brand list.
     *
     * "Independent" here means the four owner types that are not a large
     * diversified company: independent, family-owned, employee-owned, and
     * cooperative. The same grouping is used by the summary tile and by
     * pipeline/build.py, so the three cannot disagree.
     */
    function visibleBrands() {
      return data.brands.filter(function (brand) {
        if (filter === "large") return !helpers.isSmallOwner(brand.parent_type);
        if (filter === "independent") return helpers.isSmallOwner(brand.parent_type);
        return true;
      });
    }

    /* ---------------------------------------------------------------------
       Drawing
       --------------------------------------------------------------------- */

    function createMap() {
      map = L.map(container, {
        center: INITIAL_CENTER,
        zoom: INITIAL_ZOOM,
        /* Scroll-wheel zoom is off on purpose. With a full-width map in the
           middle of a scrolling article, a wheel over the map would zoom the
           map instead of scrolling the page, which traps the reader.
           Ctrl-scroll, pinch, and the +/- buttons all still zoom. */
        scrollWheelZoom: false,
        /* One finger drags the page, two fingers pan the map. Same reasoning
           as above, for touch. */
        dragging: !L.Browser.mobile,
        tap: false
      });

      /* The tile layer. The attribution string is required by both CARTO's
         terms and OpenStreetMap's licence, so it is not optional decoration.
         It also appears in the page footer. */
      L.tileLayer(
        "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
        {
          attribution:
            '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> ' +
            'contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
          subdomains: "abcd",
          maxZoom: 18
        }
      ).addTo(map);

      /* Two-finger panning needs the drag handler enabling on touch, which
         Leaflet does through its own gesture handling on mobile. */
      if (L.Browser.mobile) {
        map.dragging.enable();
      }
    }

    function draw() {
      if (overlay) {
        map.removeLayer(overlay);
      }
      overlay = L.layerGroup().addTo(map);
      drawnByBrand = {};

      var brands = visibleBrands();
      var bounds = [];

      /* --- one headquarters marker per parent ------------------------
         Several brands usually share one owner, and drawing eight markers
         on the same office is both wasteful and misleading, because the
         stack looks darker than a single one. So the HQ markers are grouped
         by parent and sized by how many visible brands they own. */
      var hqByParent = {};
      brands.forEach(function (brand) {
        if (brand.parent_hq.lat == null) return;
        var key = brand.ultimate_parent;
        if (!hqByParent[key]) {
          hqByParent[key] = {
            name: key,
            parentType: brand.parent_type,
            lat: brand.parent_hq.lat,
            lon: brand.parent_hq.lon,
            city: brand.parent_hq.city,
            state: brand.parent_hq.state,
            country: brand.parent_hq.country,
            brands: []
          };
        }
        hqByParent[key].brands.push(brand.brand);
      });

      var maxBrands = Object.keys(hqByParent).reduce(function (most, key) {
        return Math.max(most, hqByParent[key].brands.length);
      }, 1);

      /* --- the lines, drawn first so markers sit on top --------------- */
      brands.forEach(function (brand) {
        var origin = brand.brand_origin;
        var hq = brand.parent_hq;
        var color = resolveColor(helpers.colorFor(brand.parent_type));

        var entry = { line: null, origin: null, color: color };
        drawnByBrand[brand.brand] = entry;

        /* A row with no confirmed origin draws no line. Guessing a point
           would invent the very claim the row could not verify. */
        if (origin.lat == null || hq.lat == null) return;

        var sameSpot =
          Math.abs(origin.lat - hq.lat) < 0.01 &&
          Math.abs(origin.lon - hq.lon) < 0.01;

        if (!sameSpot) {
          entry.line = L.polyline(
            [[origin.lat, origin.lon], [hq.lat, hq.lon]],
            {
              className: "map__line",
              color: color,
              weight: 1.5,
              opacity: 0.55,
              interactive: true
            }
          ).addTo(overlay);

          entry.line.on("click", function () { onSelect(brand.brand); });
          entry.line.on("mouseover", function (event) {
            helpers.showTooltip(
              helpers.tooltipHTML(brand),
              event.originalEvent.clientX,
              event.originalEvent.clientY
            );
          });
          entry.line.on("mouseout", helpers.hideTooltip);
        }

        bounds.push([origin.lat, origin.lon]);
        bounds.push([hq.lat, hq.lon]);
      });

      /* --- the brand-origin markers ---------------------------------- */
      brands.forEach(function (brand) {
        var origin = brand.brand_origin;
        if (origin.lat == null) return;

        var color = resolveColor(helpers.colorFor(brand.parent_type));
        var marker = L.circleMarker([origin.lat, origin.lon], {
          radius: ORIGIN_RADIUS,
          color: color,
          weight: 2,
          /* A surface-coloured fill turns the marker into a ring, which is
             what keeps two overlapping origins readable as two things. */
          fillColor: resolveColor("var(--surface-1)"),
          fillOpacity: 1
        }).addTo(overlay);

        marker.on("click", function () { onSelect(brand.brand); });
        marker.on("mouseover", function (event) {
          helpers.showTooltip(
            helpers.tooltipHTML(brand),
            event.originalEvent.clientX,
            event.originalEvent.clientY
          );
        });
        marker.on("mouseout", helpers.hideTooltip);

        /* A keyboard- and screen-reader-accessible name for the point. */
        marker.bindTooltip(
          brand.brand + " says it is from " + origin.city +
          (origin.state ? ", " + origin.state : ""),
          { direction: "top", opacity: 0.95 }
        );

        drawnByBrand[brand.brand].origin = marker;
        bounds.push([origin.lat, origin.lon]);
      });

      /* --- the headquarters markers ---------------------------------- */
      Object.keys(hqByParent).forEach(function (key) {
        var hq = hqByParent[key];
        var color = resolveColor(helpers.colorFor(hq.parentType));

        /* Radius grows with the number of brands, on a square-root scale.
           Area is what the eye reads as quantity, and area goes with the
           square of the radius, so scaling the radius linearly would make a
           parent with four brands look sixteen times bigger than one with
           one. */
        var share = hq.brands.length / maxBrands;
        var radius = HQ_RADIUS_MIN +
          (HQ_RADIUS_MAX - HQ_RADIUS_MIN) * Math.sqrt(share);

        var marker = L.circleMarker([hq.lat, hq.lon], {
          radius: radius,
          color: resolveColor("var(--surface-1)"),
          weight: 2,
          fillColor: color,
          fillOpacity: 0.85
        }).addTo(overlay);

        var listed = hq.brands.slice(0, 10).join(", ");
        var extra = hq.brands.length > 10
          ? " and " + (hq.brands.length - 10) + " more"
          : "";

        marker.on("mouseover", function (event) {
          var html = '<div class="tooltip__title">' +
            helpers.escape(hq.name) + "</div>" +
            '<span class="tooltip__row">Headquarters: <b>' +
            helpers.escape(hq.city) +
            (hq.state ? ", " + helpers.escape(hq.state) : "") +
            (hq.country ? ", " + helpers.escape(hq.country) : "") +
            "</b></span>" +
            '<span class="tooltip__row">Type: <b>' +
            helpers.escape(helpers.labelFor(hq.parentType)) + "</b></span>" +
            '<span class="tooltip__row">Brands shown here: <b>' +
            hq.brands.length + "</b></span>" +
            '<div class="tooltip__chain">' +
            helpers.escape(listed) + extra + "</div>";
          helpers.showTooltip(
            html,
            event.originalEvent.clientX,
            event.originalEvent.clientY
          );
        });
        marker.on("mouseout", helpers.hideTooltip);

        marker.bindTooltip(
          hq.name + ", " + hq.brands.length + " brand" +
          (hq.brands.length === 1 ? "" : "s") + " here",
          { direction: "top", opacity: 0.95 }
        );

        bounds.push([hq.lat, hq.lon]);
      });

      /* Fit the view to whatever is actually on screen, so a filter that
         leaves only New England brands zooms to New England. */
      if (bounds.length) {
        map.fitBounds(bounds, { padding: [30, 30], maxZoom: 7 });
      }

      if (selectedBrand) applySelection(selectedBrand);
    }

    /* ---------------------------------------------------------------------
       Selection
       --------------------------------------------------------------------- */

    /**
     * Make one brand's line and origin marker stand out, and leave the rest
     * legible but quiet.
     *
     * Why it exists: this is the link from the tree to the map that the page
     * promises. Clicking a brand on the left of the tree should tell you
     * where on the map to look.
     */
    function applySelection(brandName) {
      Object.keys(drawnByBrand).forEach(function (name) {
        var entry = drawnByBrand[name];
        var isSelected = name === brandName;
        var anySelected = Boolean(brandName);

        if (entry.line) {
          entry.line.setStyle({
            weight: isSelected ? 3.5 : 1.5,
            opacity: isSelected ? 1 : (anySelected ? 0.12 : 0.55)
          });
          if (isSelected) entry.line.bringToFront();
        }
        if (entry.origin) {
          entry.origin.setStyle({
            weight: isSelected ? 3.5 : 2,
            opacity: isSelected ? 1 : (anySelected ? 0.25 : 1),
            radius: isSelected ? ORIGIN_RADIUS + 3 : ORIGIN_RADIUS
          });
          if (isSelected) entry.origin.bringToFront();
        }
      });

      /* Pan to the selected brand if it is off screen, without changing the
         zoom, so the reader does not lose their sense of place. */
      var entry = brandName ? drawnByBrand[brandName] : null;
      if (entry && entry.origin && !map.getBounds().contains(entry.origin.getLatLng())) {
        map.panTo(entry.origin.getLatLng());
      }
    }

    /* ---------------------------------------------------------------------
       The filter buttons
       --------------------------------------------------------------------- */

    buttons.forEach(function (button) {
      button.addEventListener("click", function () {
        filter = button.getAttribute("data-filter");
        /* aria-pressed is what tells a screen reader which of the three is
           the current view, and the stylesheet uses it to shade the active
           button, so the two can never disagree. */
        buttons.forEach(function (other) {
          other.setAttribute(
            "aria-pressed",
            String(other === button)
          );
        });
        draw();
      });
    });

    /* ---------------------------------------------------------------------
       Start
       --------------------------------------------------------------------- */

    createMap();
    draw();

    /* Leaflet resolved its colours into attributes, so a switch between
       light and dark mode needs a redraw rather than a repaint. */
    if (window.matchMedia) {
      var scheme = window.matchMedia("(prefers-color-scheme: dark)");
      var onSchemeChange = function () { draw(); };
      if (scheme.addEventListener) scheme.addEventListener("change", onSchemeChange);
      else if (scheme.addListener) scheme.addListener(onSchemeChange);
    }

    return {
      onSelect: function (brandName) {
        selectedBrand = brandName;
        applySelection(brandName);
      },

      onResize: function () {
        /* Leaflet caches the container size, so it has to be told the box
           changed or the tiles end up offset from the overlays. */
        if (map) map.invalidateSize();
      }
    };
  }

  return { init: init };
})();
