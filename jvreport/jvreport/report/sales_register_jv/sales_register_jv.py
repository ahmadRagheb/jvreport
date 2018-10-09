# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

from __future__ import unicode_literals
import frappe
from frappe.utils import getdate, cstr, flt, fmt_money
from frappe import _, _dict
from erpnext.accounts.utils import get_account_currency

def execute(filters=None):
	account_details = {}

	if filters and filters.get('print_in_account_currency') and \
		not filters.get('account'):
		frappe.throw(_("Select an account to print in account currency"))

	for acc in frappe.db.sql("""select name, is_group from tabAccount""", as_dict=1):
		account_details.setdefault(acc.name, acc)

	validate_filters(filters, account_details)

	validate_party(filters)

	filters = set_account_currency(filters)

	columns = get_columns2(filters)

	res = get_result(filters, account_details)
	# invoice_list = get_invoices(filters, additional_query_columns)

	# invocies data start here 
	invoice_list = get_invoices()
	if not invoice_list:
		msgprint(_("No record found"))
		return columns, invoice_list
	columns3, income_accounts, tax_accounts = get_columns_inv(invoice_list)

	invoice_income_map = get_invoice_income_map(invoice_list)
	invoice_income_map, invoice_tax_map = get_invoice_tax_map(invoice_list,
		invoice_income_map, income_accounts)
	#Cost Center & Warehouse Map
	invoice_cc_wh_map = get_invoice_cc_wh_map(invoice_list)
	invoice_so_dn_map = get_invoice_so_dn_map(invoice_list)
	company_currency = frappe.db.get_value("Company", filters.get("company"), "default_currency")
	mode_of_payments = get_mode_of_payments([inv.name for inv in invoice_list])

	data = []
	for inv in invoice_list:
		# invoice details
		sales_order = list(set(invoice_so_dn_map.get(inv.name, {}).get("sales_order", [])))
		delivery_note = list(set(invoice_so_dn_map.get(inv.name, {}).get("delivery_note", [])))
		cost_center = list(set(invoice_cc_wh_map.get(inv.name, {}).get("cost_center", [])))
		warehouse = list(set(invoice_cc_wh_map.get(inv.name, {}).get("warehouse", [])))

		row = [
			inv.name, inv.posting_date, inv.customer, inv.customer_name
		]

		# if additional_query_columns:
		# 	for col in additional_query_columns:
		# 		row.append(inv.get(col))

		row +=[
			inv.get("customer_group"),
			inv.get("territory"),
			inv.get("tax_id"),
			inv.debit_to, ", ".join(mode_of_payments.get(inv.name, [])),
			inv.project, inv.owner, inv.remarks,
			", ".join(sales_order), ", ".join(delivery_note),", ".join(cost_center),
			", ".join(warehouse), company_currency
		]
		# map income values
		base_net_total = 0
		income_accounts_total = []
		for income_acc in income_accounts:
			income_amount = flt(invoice_income_map.get(inv.name, {}).get(income_acc))
			base_net_total += income_amount
			#adding income to raw data
			income_accounts_total.append(income_acc)
			row.append(income_amount)

		# net total
		row.append(base_net_total or inv.base_net_total)

		# tax account
		total_tax = 0
		total_tax_accounts = []
		for tax_acc in tax_accounts:
			if tax_acc not in income_accounts:
				tax_amount = flt(invoice_tax_map.get(inv.name, {}).get(tax_acc))
				total_tax += tax_amount
				total_tax_accounts.append(tax_acc)
				row.append(tax_amount)

		# total tax, grand total, outstanding amount & rounded total
		row += [total_tax, inv.base_grand_total, inv.base_rounded_total, inv.outstanding_amount]

		data.append(row)


	# frappe.throw(str(len(data[0])))

	# frappe.msgprint(str(res))

	for inv in data :
		row = {}
		i = 16 
		row['voucher_no'] = inv[0]
		row['posting_date'] = inv[1]
		row['party'] = inv[2]
		row['customer_name'] = inv[3]
		row['customer_group'] = inv[4]
		row['territory'] = inv[5]
		row['tax_id'] = inv[6]
		row['account'] = inv[7]
		row['mode_of_payment'] = inv[8]
		row['project'] = inv[9]
		row['owner']  = inv[10]
		row['remarks']= inv[11]
		row['sales_order'] = inv[12]
		row['delivery_note'] = inv[13]
		row['cost_center'] = inv[14]
		row['warehouse'] = inv[15]
		row['company_currency'] = inv[16]

		if len(income_accounts_total)>0:
			for count,acc in enumerate(income_accounts_total,17):
				# frappe.msgprint(str(inv[count]))
				row[str(acc)] =  inv[count]		
				i += 1
		i += 1
		
		row['net_total'] = inv[i]

		if len(total_tax_accounts)>0:
			i+=1
			for count,acc in enumerate(total_tax_accounts,i):
				row[acc] =  inv[count]
				i += 1
		i+=1
		for x in range(i, i+3):
			row['total_tax'] = inv[x]
			row['grand_total'] = inv[x]
			row['rounded_total'] = inv[x]
			row['outstanding_amount'] = inv[x]
		res.append(row)


	# frappe.msgprint(str(total_tax_accounts))
	if len(income_accounts_total)>0:
		for count,acc in enumerate(income_accounts_total,17):
			col ={
				"label": _(str(acc)),
				"fieldname": str(acc),
				"width": 100
			}
			columns = columns[:count] + [col] + columns[count:]

	tax_index=0	

	for count, x in enumerate(columns):
		if x['fieldname']=="net_total":
			tax_index = count+1
			# frappe.msgprint(str(tax_index))
			break 
	if len(total_tax_accounts)>0:
		for count,acc in enumerate(total_tax_accounts,tax_index):
			col ={
				"label": _(str(acc)),
				"fieldname": str(acc),
				"width": 100
			}
			columns = columns[:count] + [col] + columns[count:]

	#get end of tax coloumns
	count_tax = 0 
	for count, x in enumerate(columns):
		if x['fieldname']=="total_tax":
			count_tax = count
			break 

	#gl tax changes in col
	voucher_no_list = []
	voucher_no_dict = []
	tax_list_for_del = []
	for count,gl_dict in enumerate(res):
		if 'account_type' in gl_dict:
			if gl_dict['account_type'] == 'Tax':
				voucher_no_list.append(gl_dict['voucher_no'])
				voucher_no_dict.append({
					"voucher_no":gl_dict['voucher_no'],
					"account":gl_dict['account'],
					"amount":gl_dict['credit']
					})
				tax_list_for_del.append(count)
				col ={
					"label": _(str(gl_dict['account'])),
					"fieldname": str(gl_dict['account']),
					"width": 100
					}
				columns = columns[:count_tax] + [col] + columns[count_tax:]


				# frappe.msgprint(str(count_tax))
	for index in tax_list_for_del:
		del res[index]
	if len(voucher_no_list)>0:
		for gl_dict in res:
			if 'voucher_no' in gl_dict:
				if gl_dict['voucher_no'] in voucher_no_list:
					for vnd in voucher_no_dict:
						if vnd['voucher_no'] == gl_dict['voucher_no']:
							gl_dict[str(vnd["account"])] = vnd['amount']

	# frappe.throw(str(res))
	return columns, res


def get_invoice_so_dn_map(invoice_list):
	si_items = frappe.db.sql("""select parent, sales_order, delivery_note, so_detail
		from `tabSales Invoice Item` where parent in (%s)
		and (ifnull(sales_order, '') != '' or ifnull(delivery_note, '') != '')""" %
		', '.join(['%s']*len(invoice_list)), tuple([inv.name for inv in invoice_list]), as_dict=1)

	invoice_so_dn_map = {}
	for d in si_items:
		if d.sales_order:
			invoice_so_dn_map.setdefault(d.parent, frappe._dict()).setdefault(
				"sales_order", []).append(d.sales_order)

		delivery_note_list = None
		if d.delivery_note:
			delivery_note_list = [d.delivery_note]
		elif d.sales_order:
			delivery_note_list = frappe.db.sql_list("""select distinct parent from `tabDelivery Note Item`
				where docstatus=1 and so_detail=%s""", d.so_detail)

		if delivery_note_list:
			invoice_so_dn_map.setdefault(d.parent, frappe._dict()).setdefault("delivery_note", delivery_note_list)

	return invoice_so_dn_map


def get_invoice_cc_wh_map(invoice_list):
	si_items = frappe.db.sql("""select parent, cost_center, warehouse
		from `tabSales Invoice Item` where parent in (%s)
		and (ifnull(cost_center, '') != '' or ifnull(warehouse, '') != '')""" %
		', '.join(['%s']*len(invoice_list)), tuple([inv.name for inv in invoice_list]), as_dict=1)

	invoice_cc_wh_map = {}
	for d in si_items:
		if d.cost_center:
			invoice_cc_wh_map.setdefault(d.parent, frappe._dict()).setdefault(
				"cost_center", []).append(d.cost_center)

		if d.warehouse:
			invoice_cc_wh_map.setdefault(d.parent, frappe._dict()).setdefault(
				"warehouse", []).append(d.warehouse)

	return invoice_cc_wh_map

def get_mode_of_payments(invoice_list):
	mode_of_payments = {}
	if invoice_list:
		inv_mop = frappe.db.sql("""select parent, mode_of_payment
			from `tabSales Invoice Payment` where parent in (%s) group by parent, mode_of_payment""" %
			', '.join(['%s']*len(invoice_list)), tuple(invoice_list), as_dict=1)

		for d in inv_mop:
			mode_of_payments.setdefault(d.parent, []).append(d.mode_of_payment)

	return mode_of_payments

def get_invoice_income_map(invoice_list):
	income_details = frappe.db.sql("""select parent, income_account, sum(base_net_amount) as amount
		from `tabSales Invoice Item` where parent in (%s) group by parent, income_account""" %
		', '.join(['%s']*len(invoice_list)), tuple([inv.name for inv in invoice_list]), as_dict=1)

	invoice_income_map = {}
	for d in income_details:
		invoice_income_map.setdefault(d.parent, frappe._dict()).setdefault(d.income_account, [])
		invoice_income_map[d.parent][d.income_account] = flt(d.amount)

	return invoice_income_map

def get_invoice_tax_map(invoice_list, invoice_income_map, income_accounts):
	tax_details = frappe.db.sql("""select parent, account_head,
		sum(base_tax_amount_after_discount_amount) as tax_amount
		from `tabSales Taxes and Charges` where parent in (%s) group by parent, account_head""" %
		', '.join(['%s']*len(invoice_list)), tuple([inv.name for inv in invoice_list]), as_dict=1)

	invoice_tax_map = {}
	for d in tax_details:
		if d.account_head in income_accounts:
			if invoice_income_map[d.parent].has_key(d.account_head):
				invoice_income_map[d.parent][d.account_head] += flt(d.tax_amount)
			else:
				invoice_income_map[d.parent][d.account_head] = flt(d.tax_amount)
		else:
			invoice_tax_map.setdefault(d.parent, frappe._dict()).setdefault(d.account_head, [])
			invoice_tax_map[d.parent][d.account_head] = flt(d.tax_amount)

	return invoice_income_map, invoice_tax_map

def get_invoices():
	# if additional_query_columns:
	# 	additional_query_columns = ', ' + ', '.join(additional_query_columns)

	# conditions = get_conditions(filters)
	return frappe.db.sql("""
		select name, posting_date, debit_to, project, customer, 
		customer_name, owner, remarks, territory, tax_id, customer_group,
		base_net_total, base_grand_total, base_rounded_total, outstanding_amount 
		from `tabSales Invoice`
		where docstatus = 1  order by posting_date desc, name desc""", as_dict=1)



def validate_filters(filters, account_details):
	if not filters.get('company'):
		frappe.throw(_('{0} is mandatory').format(_('Company')))

	if filters.get("account") and not account_details.get(filters.account):
		frappe.throw(_("Account {0} does not exists").format(filters.account))

	if filters.get("account") and filters.get("group_by_account") \
			and account_details[filters.account].is_group == 0:
		frappe.throw(_("Can not filter based on Account, if grouped by Account"))

	if filters.get("voucher_no") and filters.get("group_by_voucher"):
		frappe.throw(_("Can not filter based on Voucher No, if grouped by Voucher"))

	if filters.from_date > filters.to_date:
		frappe.throw(_("From Date must be before To Date"))


def validate_party(filters):
	party_type, party = filters.get("party_type"), filters.get("party")

	if party:
		if not party_type:
			frappe.throw(_("To filter based on Party, select Party Type first"))
		elif not frappe.db.exists(party_type, party):
			frappe.throw(_("Invalid {0}: {1}").format(party_type, party))

def set_account_currency(filters):
	if not (filters.get("account") or filters.get("party")):
		return filters
	else:
		filters["company_currency"] = frappe.db.get_value("Company", filters.company, "default_currency")
		account_currency = None

		if filters.get("account"):
			account_currency = get_account_currency(filters.account)
		elif filters.get("party"):
			gle_currency = frappe.db.get_value("GL Entry", {"party_type": filters.party_type,
				"party": filters.party, "company": filters.company}, "account_currency")
			if gle_currency:
				account_currency = gle_currency
			else:
				account_currency = (None if filters.party_type in ["Employee", "Student", "Shareholder", "Member"] else
					frappe.db.get_value(filters.party_type, filters.party, "default_currency"))

		filters["account_currency"] = account_currency or filters.company_currency

		if filters.account_currency != filters.company_currency:
			filters["show_in_account_currency"] = 1

		return filters

def get_result(filters, account_details):
	gl_entries = get_gl_entries(filters)

	data = get_data_with_opening_closing(filters, account_details, gl_entries)

	result = get_result_as_list(data, filters)

	return result

def get_gl_entries(filters):
	select_fields = """, sum(gl.debit_in_account_currency) as debit_in_account_currency,
		sum(gl.credit_in_account_currency) as credit_in_account_currency""" \
		if filters.get("show_in_account_currency") else ""

	group_by_condition = "group by gl.voucher_type, gl.voucher_no, gl.account, gl.cost_center" \
		if filters.get("group_by_voucher") else "group by gl.name"

	gl_entries = frappe.db.sql("""
		select
			 gl.voucher_no, gl.posting_date, gl.account
			 ,acc.account_type,gl.party_type, gl.party,
			sum(gl.debit) as debit, sum(gl.credit) as credit,
			gl.voucher_type, gl.cost_center, gl.project,
			gl.against_voucher_type, gl.against_voucher,
			gl.remarks, gl.against, gl.is_opening {select_fields},
			c.customer_name,c.customer_group,c.territory,c.tax_id,
			je.owner
		from `tabGL Entry` as gl ,`tabJournal Entry` as je, 
		`tabCustomer` as c,`tabAccount` as acc
		where gl.voucher_type="Journal Entry" and je.sales_register="1"
		and gl.account = acc.name
		and gl.voucher_no = je.name and gl.company=%(company)s {conditions}
		{group_by_condition}
		order by gl.posting_date, gl.account"""\
		.format(select_fields=select_fields, 
			conditions=get_conditions(filters),
			group_by_condition=group_by_condition), filters, as_dict=1)


	return gl_entries

def get_conditions(filters):
	conditions = []
	if filters.get("account"):
		lft, rgt = frappe.db.get_value("Account", filters["account"], ["lft", "rgt"])
		conditions.append("""gl.account in (select name from tabAccount
			where lft>=%s and rgt<=%s and docstatus<2)""" % (lft, rgt))

	if filters.get("voucher_no"):
		conditions.append("gl.voucher_no=%(voucher_no)s")

	if filters.get("party_type"):
		conditions.append("gl.party_type=%(party_type)s")

	if filters.get("party"):
		conditions.append("gl.party=%(party)s")

	if not (filters.get("account") or filters.get("party") or filters.get("group_by_account")):
		conditions.append("gl.posting_date >=%(from_date)s")

	if filters.get("project"):
		conditions.append("gl.project=%(project)s")

	from frappe.desk.reportview import build_match_conditions
	match_conditions = build_match_conditions("GL Entry")
	if match_conditions: conditions.append(match_conditions)

	return "and {}".format(" and ".join(conditions)) if conditions else ""

def get_data_with_opening_closing(filters, account_details, gl_entries):
	data = []
	gle_map = initialize_gle_map(gl_entries)

	totals, entries = get_accountwise_gle(filters, gl_entries, gle_map)

	# Opening for filtered account
	# data.append(totals.opening)

	if filters.get("group_by_account"):
		for acc, acc_dict in gle_map.items():
			if acc_dict.entries:
				# opening
				data.append({})
				data.append(acc_dict.totals.opening)

				data += acc_dict.entries

				# totals
				data.append(acc_dict.totals.total)

				# closing
				data.append(acc_dict.totals.closing)
		data.append({})

	else:
		data += entries

	# totals
	# data.append(totals.total)

	# closing
	# data.append(totals.closing)

	return data

def get_totals_dict():
	def _get_debit_credit_dict(label):
		return _dict(
			account = "'{0}'".format(label),
			debit = 0.0,
			credit = 0.0,
			debit_in_account_currency = 0.0,
			credit_in_account_currency = 0.0
		)
	return _dict(
		opening = _get_debit_credit_dict(_('Opening')),
		total = _get_debit_credit_dict(_('Total')),
		closing = _get_debit_credit_dict(_('Closing (Opening + Total)'))
	)

def initialize_gle_map(gl_entries):
	gle_map = frappe._dict()
	for gle in gl_entries:
		gle_map.setdefault(gle.account, _dict(totals = get_totals_dict(), entries = []))
	return gle_map

def get_accountwise_gle(filters, gl_entries, gle_map):
	totals = get_totals_dict()
	entries = []

	def update_value_in_dict(data, key, gle):
		data[key].debit += flt(gle.debit)
		data[key].credit += flt(gle.credit)

		data[key].debit_in_account_currency += flt(gle.debit_in_account_currency)
		data[key].credit_in_account_currency += flt(gle.credit_in_account_currency)


	from_date, to_date = getdate(filters.from_date), getdate(filters.to_date)
	for gle in gl_entries:
		if gle.posting_date < from_date or cstr(gle.is_opening) == "Yes":
			update_value_in_dict(gle_map[gle.account].totals, 'opening', gle)
			update_value_in_dict(totals, 'opening', gle)
			
			update_value_in_dict(gle_map[gle.account].totals, 'closing', gle)
			update_value_in_dict(totals, 'closing', gle)

		elif gle.posting_date <= to_date:
			update_value_in_dict(gle_map[gle.account].totals, 'total', gle)
			update_value_in_dict(totals, 'total', gle)
			if filters.get("group_by_account"):
				gle_map[gle.account].entries.append(gle)
			else:
				entries.append(gle)

			update_value_in_dict(gle_map[gle.account].totals, 'closing', gle)
			update_value_in_dict(totals, 'closing', gle)

	return totals, entries

def get_result_as_list(data, filters):
	balance, balance_in_account_currency = 0, 0
	inv_details = get_supplier_invoice_details()

	for d in data:
		if not d.get('posting_date'):
			balance, balance_in_account_currency = 0, 0

		balance = get_balance(d, balance, 'debit', 'credit')
		d['balance'] = balance

		if filters.get("show_in_account_currency"):
			balance_in_account_currency = get_balance(d, balance_in_account_currency,
				'debit_in_account_currency', 'credit_in_account_currency')
			d['balance_in_account_currency'] = balance_in_account_currency
		else:
			d['debit_in_account_currency'] = d.get('debit', 0)
			d['credit_in_account_currency'] = d.get('credit', 0)
			d['balance_in_account_currency'] = d.get('balance')

		d['account_currency'] = filters.account_currency
		d['bill_no'] = inv_details.get(d.get('against_voucher'), '')

	return data

def get_supplier_invoice_details():
	inv_details = {}
	for d in frappe.db.sql(""" select name, bill_no from `tabPurchase Invoice`
		where docstatus = 1 and bill_no is not null and bill_no != '' """, as_dict=1):
		inv_details[d.name] = d.bill_no

	return inv_details

def get_balance(row, balance, debit_field, credit_field):
	balance += (row.get(debit_field, 0) -  row.get(credit_field, 0))

	return balance

def get_columns2(filters):
	columns = [
		{
			"label": _("Voucher No"),
			"fieldname": "voucher_no",
			"fieldtype": "Dynamic Link",
			"options": "voucher_type",
			"width": 100
		},
		{
			"label": _("Posting Date"),
			"fieldname": "posting_date",
			"fieldtype": "Date",
			"width": 90
		},
		{
			"label": _("Customer"),
			"fieldname": "party",
			"width": 100
		},
		{
			"label": _("Customer Name"),
			"fieldname": "customer_name",
			"width": 100
		},
		{
			"label": _("Customer Group"),
			"fieldname": "customer_group",
			"width": 100
		},
		{
			"label": _("Territory"),
			"fieldname": "territory",
			"width": 100
		},
		{
			"label": _("Tax Id"),
			"fieldname": "tax_id",
			"width": 100
		},
		{
			"label": _("Account"),
			"fieldname": "account",
			"fieldtype": "Link",
			"options": "Account",
			"width": 180
		},
		{
			"label": _("Mode of Payment"),
			"fieldname": "mode_of_payment",
			"width": 100
		},
		{
			"label": _("Project"),
			"options": "Project",
			"fieldname": "project",
			"width": 100
		},
		{
			"label": _("Owner"),
			"fieldname": "owner",
			"width": 150
		},
		{
			"label": _("Remarks"),
			"fieldname": "remarks",
			"width": 400
		},
		{
			"label": _("Sales Order"),
			"fieldname": "sales_order",
			"width": 100
		},
		{
			"label": _("Delivery Note"),
			"fieldname": "delivery_note",
			"width": 100
		},		
		{
			"label": _("Cost Center"),
			"fieldname": "cost_center",
			"width": 100
		},
		{
			"label": _("Warehouse"),
			"fieldname": "warehouse",
			"width": 100
		},
		{
			"label": _("Currency"),
			"fieldname": "company_currency",
			"width": 100
		},
		{
			"label": _("Net Total"),
			"fieldname": "net_total",
			"width": 100
		},
		{
			"label": _("Total Tax"),
			"fieldname": "total_tax",
			"width": 100
		},
		{
			"label": _("Grand Total"),
			"fieldname": "grand_total",
			"width": 100
		},
		{
			"label": _("Rounded Total"),
			"fieldname": "rounded_total",
			"width": 100
		},
		{
			"label": _("Outstanding Amount"),
			"fieldname": "outstanding_amount",
			"width": 100
		},

		{
			"label": _("Debit"),
			"fieldname": "debit",
			"fieldtype": "Float",
			"width": 100
		},
		{
			"label": _("Credit"),
			"fieldname": "credit",
			"fieldtype": "Float",
			"width": 100
		},
		{
			"label": _("Balance (Dr - Cr)"),
			"fieldname": "balance",
			"fieldtype": "Float",
			"width": 130
		}
	]

	if filters.get("show_in_account_currency"):
		columns.extend([
			{
				"label": _("Debit") + " (" + filters.account_currency + ")",
				"fieldname": "debit_in_account_currency",
				"fieldtype": "Float",
				"width": 100
			},
			{
				"label": _("Credit") + " (" + filters.account_currency + ")",
				"fieldname": "credit_in_account_currency",
				"fieldtype": "Float",
				"width": 100
			},
			{
				"label": _("Balance") + " (" + filters.account_currency + ")",
				"fieldname": "balance_in_account_currency",
				"fieldtype": "Data",
				"width": 100
			}
		])

	columns.extend([
		{
			"label": _("Against Account"),
			"fieldname": "against",
			"width": 120
		},

	])

	return columns

def get_columns_inv(invoice_list):
	"""return columns based on filters"""
	columns = [
		_("Invoice") + ":Link/Sales Invoice:120", _("Posting Date") + ":Date:80",
		_("Customer") + ":Link/Customer:120", _("Customer Name") + "::120"
	]

	columns +=[
		_("Customer Group") + ":Link/Customer Group:120", _("Territory") + ":Link/Territory:80",
		_("Tax Id") + "::80", _("Receivable Account") + ":Link/Account:120", _("Mode of Payment") + "::120",
		_("Project") +":Link/Project:80", _("Owner") + "::150", _("Remarks") + "::150",
		_("Sales Order") + ":Link/Sales Order:100", _("Delivery Note") + ":Link/Delivery Note:100",
		_("Cost Center") + ":Link/Cost Center:100", _("Warehouse") + ":Link/Warehouse:100",
		{
			"fieldname": "currency",
			"label": _("Currency"),
			"fieldtype": "Data",
			"width": 80
		}
	]

	income_accounts = tax_accounts = income_columns = tax_columns = []

	if invoice_list:
		income_accounts = frappe.db.sql_list("""select distinct income_account
			from `tabSales Invoice Item` where docstatus = 1 and parent in (%s)
			order by income_account""" %
			', '.join(['%s']*len(invoice_list)), tuple([inv.name for inv in invoice_list]))

		tax_accounts = 	frappe.db.sql_list("""select distinct account_head
			from `tabSales Taxes and Charges` where parenttype = 'Sales Invoice'
			and docstatus = 1 and base_tax_amount_after_discount_amount != 0
			and parent in (%s) order by account_head""" %
			', '.join(['%s']*len(invoice_list)), tuple([inv.name for inv in invoice_list]))

	income_columns = [(account + ":Currency/currency:120") for account in income_accounts]
	for account in tax_accounts:
		if account not in income_accounts:
			tax_columns.append(account + ":Currency/currency:120")

	columns = columns + income_columns + [_("Net Total") + ":Currency/currency:120"] + tax_columns + \
		[_("Total Tax") + ":Currency/currency:120", _("Grand Total") + ":Currency/currency:120",
		_("Rounded Total") + ":Currency/currency:120", _("Outstanding Amount") + ":Currency/currency:120"]

	return columns, income_accounts, tax_accounts

