/* =========================================================================
   tree.js — the ownership tree, drawn as a Sankey diagram.

   Why this view exists
   --------------------
   The dataset's main finding is about concentration: a long list of brands
   on one side, a short list of owners on the other. A table can state that
   and a bar chart can measure it, but neither lets you *see* it. A Sankey
   does, because the many-to-few shape is the picture.

   What a Sankey is, if you have not met one
   -----------------------------------------
   Think of water in pipes. Every brand on the left is a pipe carrying one
   unit. Pipes merge as they flow right, so the pipe arriving at a parent
   company is as thick as the number of brands feeding it. Wide bands on the
   right mean concentration. Lots of thin bands spread evenly would mean the
   opposite, and the chart would show that just as plainly.

   Why the plugin
   --------------
   D3 itself does not include a Sankey layout. `d3-sankey` is the official
   plugin that does the hard part: deciding the vertical order of the nodes
   so the ribbons cross as little as possible. It is loaded from a CDN in
   index.html and attaches itself to the global `d3` object.

   This file exposes one thing, `window.OwnershipTree.init(options)`, and
   returns an object with `onSelect` and `onResize` so the page can drive it.
   ========================================================================= */

window.OwnershipTree = (function () {
  "use strict";

  /* Layout constants. Pulled out so the whole shape of the chart can be
     tuned from one place. */
  var NODE_WIDTH = 13;        // thickness of the little bars at each end
  var NODE_PADDING = 3;       // vertical gap between two stacked nodes
  var ROW_HEIGHT = 15;        // vertical room allowed per brand
  var MIN_HEIGHT = 420;
  var MIN_WIDTH = 640;        // below this the labels stop fitting, so scroll
  var MARGIN = { top: 34, right: 200, bottom: 16, left: 168 };

  /* -----------------------------------------------------------------------
     Data preparation
     ----------------------------------------------------------------------- */

  /**
   * Build the node and link arrays that d3-sankey expects.
   *
   * Why it exists: d3-sankey wants a flat list of nodes and a list of links
   * that reference nodes by index. Our JSON is a list of brands, each naming
   * its parent. This translates one into the other.
   *
   * The order of the brand nodes matters. Brands are emitted grouped by
   * parent, with the largest parent first, and the layout is then told not
   * to re-sort. That gives clean bundles with few crossings, and it is more
   * legible than letting the layout order 45 equal-valued nodes arbitrarily.
   */
  function buildGraph(data, helpers) {
    var nodes = [];
    var links = [];
    var indexByKey = {};

    function addNode(node) {
      indexByKey[node.key] = nodes.length;
      nodes.push(node);
      return nodes.length - 1;
    }

    /* Parents in the order build.py ranked them: most brands first. */
    data.parents.forEach(function (parent) {
      /* Every brand of this parent, in alphabetical order within the group. */
      var brandsOfParent = data.brands.filter(function (brand) {
        return brand.ultimate_parent === parent.name;
      }).sort(function (a, b) {
        return a.brand.localeCompare(b.brand);
      });

      brandsOfParent.forEach(function (brand) {
        addNode({
          key: "brand:" + brand.brand,
          name: brand.brand,
          side: "brand",
          brand: brand,
          parentType: brand.parent_type
        });
      });
    });

    /* Parent nodes come after all brand nodes. d3-sankey works out which
       column each belongs in from the links, not from this order. */
    data.parents.forEach(function (parent) {
      addNode({
        key: "parent:" + parent.name,
        name: parent.name,
        side: "parent",
        parent: parent,
        parentType: parent.parent_type
      });
    });

    data.brands.forEach(function (brand) {
      var source = indexByKey["brand:" + brand.brand];
      var target = indexByKey["parent:" + brand.ultimate_parent];
      if (source === undefined || target === undefined) return;
      links.push({
        source: source,
        target: target,
        value: 1,
        brand: brand,
        parentType: brand.parent_type,
        color: helpers.colorFor(brand.parent_type)
      });
    });

    return { nodes: nodes, links: links };
  }

  /* -----------------------------------------------------------------------
     The view
     ----------------------------------------------------------------------- */

  function init(options) {
    var container = options.container;
    var data = options.data;
    var helpers = options.helpers;
    var onSelect = options.onSelect;

    /* Nothing to draw, and saying so is better than an empty box. */
    if (!data.brands.length) {
      container.innerHTML = '<p class="state">No brands in the dataset yet.</p>';
      return {};
    }

    /* Selections kept on the closure so onSelect and onResize can reach
       them without re-querying the DOM. */
    var svg = null;
    var nodeSel = null;
    var linkSel = null;
    var labelSel = null;
    var selectedBrand = null;

    function draw() {
      /* Width comes from the container, with a floor. Below the floor the
         chart keeps its minimum width and the wrapper scrolls sideways,
         which is what makes this readable on a phone without shrinking the
         labels to nothing. */
      var available = container.clientWidth || MIN_WIDTH;
      var width = Math.max(MIN_WIDTH, available);
      var height = Math.max(
        MIN_HEIGHT,
        data.brands.length * ROW_HEIGHT + MARGIN.top + MARGIN.bottom
      );

      var graph = buildGraph(data, helpers);

      /* d3.sankey() builds the layout generator. Reading the chained calls:
           nodeWidth      how thick the end bars are
           nodePadding    the gap between stacked nodes
           nodeSort(null) keep the input order, which we chose deliberately
           extent         the rectangle the diagram is laid out inside */
      var sankey = d3.sankey()
        .nodeWidth(NODE_WIDTH)
        .nodePadding(NODE_PADDING)
        .nodeSort(null)
        .extent([
          [MARGIN.left, MARGIN.top],
          [width - MARGIN.right, height - MARGIN.bottom]
        ]);

      /* Calling it mutates the graph, adding x0/x1/y0/y1 to every node and a
         width and path to every link. */
      var laidOut = sankey({
        nodes: graph.nodes.map(function (d) { return Object.assign({}, d); }),
        links: graph.links.map(function (d) { return Object.assign({}, d); })
      });

      container.innerHTML = "";
      svg = d3.select(container)
        .append("svg")
        .attr("width", width)
        .attr("height", height)
        .attr("viewBox", "0 0 " + width + " " + height)
        .attr("role", "img")
        .attr("aria-label",
          "Sankey diagram. " + data.brands.length + " breakfast brands on the " +
          "left flow into " + data.parents.length + " ultimate parent companies " +
          "on the right. The full data is in the table below this chart.");

      /* Column headings, so the two sides are named rather than guessed. */
      svg.append("text")
        .attr("class", "sankey__axis-label")
        .attr("x", MARGIN.left - 8)
        .attr("y", 18)
        .attr("text-anchor", "end")
        .text("Brand");

      svg.append("text")
        .attr("class", "sankey__axis-label")
        .attr("x", width - MARGIN.right + 8)
        .attr("y", 18)
        .text("Owned by");

      /* --- links ------------------------------------------------------
         Drawn before the nodes so the nodes sit on top of them. Each link
         carries its parent's colour, so the eye follows colour across the
         whole width and the merging is visible, not just implied. */
      linkSel = svg.append("g")
        .attr("fill", "none")
        .selectAll("path")
        .data(laidOut.links)
        .join("path")
        .attr("class", "sankey__link")
        .attr("d", d3.sankeyLinkHorizontal())
        .attr("stroke", function (d) { return d.color; })
        /* Every ribbon is at least 1px, so a single-brand parent still has a
           visible thread rather than a hairline that disappears. */
        .attr("stroke-width", function (d) { return Math.max(1, d.width); });

      /* --- nodes ------------------------------------------------------
         Parent nodes wear their owner-type colour. Brand nodes stay grey on
         purpose: a brand is not an ownership type, and colouring it would
         imply the brand itself has that property. */
      nodeSel = svg.append("g")
        .selectAll("rect")
        .data(laidOut.nodes)
        .join("rect")
        .attr("class", "sankey__node")
        .attr("x", function (d) { return d.x0; })
        .attr("y", function (d) { return d.y0; })
        .attr("width", function (d) { return d.x1 - d.x0; })
        .attr("height", function (d) { return Math.max(2, d.y1 - d.y0); })
        .attr("rx", 2)
        .attr("fill", function (d) {
          return d.side === "parent"
            ? helpers.colorFor(d.parentType)
            : "var(--node-brand)";
        })
        .attr("tabindex", 0)
        .attr("role", "button")
        .attr("aria-label", function (d) {
          return d.side === "brand"
            ? d.name + ", owned by " + d.brand.ultimate_parent
            : d.name + ", owns " + d.parent.brand_count + " brands in this dataset";
        });

      /* --- labels -----------------------------------------------------
         Every node is directly labelled. That is not decoration: three of
         the seven colours fall below 3:1 contrast on the light surface, and
         a direct label is what makes the identity readable anyway. */
      labelSel = svg.append("g")
        .selectAll("text")
        .data(laidOut.nodes)
        .join("text")
        .attr("class", function (d) {
          return "sankey__label" + (d.side === "parent" ? " sankey__label--parent" : "");
        })
        .attr("x", function (d) { return d.side === "brand" ? d.x0 - 7 : d.x1 + 7; })
        .attr("y", function (d) { return (d.y0 + d.y1) / 2; })
        .attr("dy", "0.34em")
        .attr("text-anchor", function (d) { return d.side === "brand" ? "end" : "start"; })
        .text(function (d) {
          if (d.side === "brand") return d.name;
          /* The parent side shows the count, because that is the number the
             chart is about. */
          return d.name + "  (" + d.parent.brand_count + ")";
        });

      /* --- interaction ------------------------------------------------ */

      nodeSel
        .on("mouseenter", function (event, d) { hoverNode(event, d); })
        .on("focus", function (event, d) { hoverNode(event, d); })
        .on("mousemove", function (event, d) {
          helpers.showTooltip(tooltipFor(d), event.clientX, event.clientY);
        })
        .on("mouseleave", clearHover)
        .on("blur", clearHover)
        .on("click", function (event, d) {
          if (d.side === "brand") onSelect(d.name);
        })
        .on("keydown", function (event, d) {
          /* Enter and Space activate a button, so a keyboard user can select
             a brand without a mouse. */
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            if (d.side === "brand") onSelect(d.name);
          }
        });

      /* Hovering a ribbon is easier than hitting a thin node on a phone, so
         the ribbons answer to the pointer too. */
      linkSel
        .on("mouseenter", function (event, d) {
          highlight(function (link) { return link.brand.brand === d.brand.brand; });
          helpers.showTooltip(helpers.tooltipHTML(d.brand), event.clientX, event.clientY);
        })
        .on("mousemove", function (event, d) {
          helpers.showTooltip(helpers.tooltipHTML(d.brand), event.clientX, event.clientY);
        })
        .on("mouseleave", clearHover)
        .on("click", function (event, d) { onSelect(d.brand.brand); });

      /* Re-apply an existing selection after a redraw, so a resize does not
         silently drop the reader's highlight. */
      if (selectedBrand) applySelection(selectedBrand);
    }

    /* -------------------------------------------------------------------
       Hover and highlight
       ------------------------------------------------------------------- */

    function tooltipFor(node) {
      if (node.side === "brand") return helpers.tooltipHTML(node.brand);

      /* A parent's card lists the brands it owns here, capped so a large
         owner does not produce a card taller than the screen. */
      var parent = node.parent;
      var shown = parent.brands.slice(0, 12);
      var html = '<div class="tooltip__title">' + helpers.escape(parent.name) + "</div>";
      html += '<span class="tooltip__row">Type: <b>' +
        helpers.escape(helpers.labelFor(parent.parent_type)) + "</b></span>";
      if (parent.hq.city) {
        html += '<span class="tooltip__row">Headquarters: <b>' +
          helpers.escape(parent.hq.city) +
          (parent.hq.state ? ", " + helpers.escape(parent.hq.state) : "") +
          "</b></span>";
      }
      html += '<span class="tooltip__row">Brands in this dataset: <b>' +
        parent.brand_count + "</b></span>";
      html += '<div class="tooltip__chain">' +
        helpers.escape(shown.join(", ")) +
        (parent.brands.length > shown.length
          ? " and " + (parent.brands.length - shown.length) + " more"
          : "") +
        "</div>";
      html += '<span class="tooltip__hint">Count is brands in this dataset, ' +
        "not every brand the company owns.</span>";
      return html;
    }

    function hoverNode(event, d) {
      if (d.side === "brand") {
        highlight(function (link) { return link.brand.brand === d.name; });
      } else {
        highlight(function (link) { return link.brand.ultimate_parent === d.name; });
      }
      helpers.showTooltip(tooltipFor(d), event.clientX, event.clientY);
    }

    /**
     * Dim everything except the links a predicate accepts, and the nodes at
     * either end of them.
     *
     * Why it exists: with 45 ribbons on screen, following one by eye is
     * hard. Dimming the rest is the cheapest way to answer "where does this
     * one go", and it changes opacity rather than colour, so the colour
     * encoding keeps meaning exactly one thing.
     */
    function highlight(matches) {
      if (!linkSel) return;

      var keepNodes = {};
      linkSel.each(function (d) {
        if (matches(d)) {
          keepNodes["brand:" + d.brand.brand] = true;
          keepNodes["parent:" + d.brand.ultimate_parent] = true;
        }
      });

      linkSel
        .classed("is-active", function (d) { return matches(d); })
        .classed("is-dimmed", function (d) { return !matches(d); });

      nodeSel.classed("is-dimmed", function (d) { return !keepNodes[d.key]; });
      labelSel
        .classed("is-active", function (d) { return Boolean(keepNodes[d.key]); })
        .classed("is-dimmed", function (d) { return !keepNodes[d.key]; });
    }

    function clearHighlight() {
      if (!linkSel) return;
      linkSel.classed("is-active", false).classed("is-dimmed", false);
      nodeSel.classed("is-dimmed", false);
      labelSel.classed("is-active", false).classed("is-dimmed", false);
    }

    function clearHover() {
      helpers.hideTooltip();
      /* A selection outlives a hover, so returning to it is the right
         resting state rather than clearing everything. */
      if (selectedBrand) applySelection(selectedBrand);
      else clearHighlight();
    }

    function applySelection(brandName) {
      highlight(function (link) { return link.brand.brand === brandName; });
    }

    /* -------------------------------------------------------------------
       The interface the page drives
       ------------------------------------------------------------------- */

    draw();

    return {
      /** Called when any view changes the selected brand. */
      onSelect: function (brandName) {
        selectedBrand = brandName;
        if (brandName) applySelection(brandName);
        else clearHighlight();
      },

      /** Called after the window has finished resizing. */
      onResize: draw
    };
  }

  return { init: init };
})();
