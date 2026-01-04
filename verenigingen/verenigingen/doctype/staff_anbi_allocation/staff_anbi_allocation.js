// Copyright (c) 2025, NVV and contributors
// For license information, please see license.txt

frappe.ui.form.on("Staff ANBI Allocation", {
	refresh: function (frm) {
		frm.trigger("update_percentage_indicator");
	},

	pct_doelstelling: function (frm) {
		frm.trigger("calculate_amounts");
		frm.trigger("update_percentage_indicator");
	},

	pct_werving: function (frm) {
		frm.trigger("calculate_amounts");
		frm.trigger("update_percentage_indicator");
	},

	pct_beheer: function (frm) {
		frm.trigger("calculate_amounts");
		frm.trigger("update_percentage_indicator");
	},

	annual_employer_cost: function (frm) {
		frm.trigger("calculate_amounts");
	},

	calculate_amounts: function (frm) {
		let cost = frm.doc.annual_employer_cost || 0;

		frm.set_value(
			"amount_doelstelling",
			(cost * (frm.doc.pct_doelstelling || 0)) / 100
		);
		frm.set_value(
			"amount_werving",
			(cost * (frm.doc.pct_werving || 0)) / 100
		);
		frm.set_value("amount_beheer", (cost * (frm.doc.pct_beheer || 0)) / 100);
	},

	update_percentage_indicator: function (frm) {
		let total =
			(frm.doc.pct_doelstelling || 0) +
			(frm.doc.pct_werving || 0) +
			(frm.doc.pct_beheer || 0);

		let indicator_class = "orange";
		if (Math.abs(total - 100) < 0.01) {
			indicator_class = "green";
		} else if (total > 100) {
			indicator_class = "red";
		}

		frm.dashboard.set_headline(
			`<span class="indicator ${indicator_class}">
				Allocation Total: ${total.toFixed(1)}%
				${Math.abs(total - 100) < 0.01 ? "&#10003;" : "(must equal 100%)"}
			</span>`
		);
	},
});
