{
	'name': "Purchase Invoice Inventory",
	'version': '1.0',
	'category': '',
	'author': "Onedoos",
	'website': 'https://www.onedoos.com',
	'description': """
		Vendor Validation, Stocks etc.
	""",
	'depends': ['account', 'account_accountant', 'stock'],
	'data': [
		'views/account_invoice_view.xml',
	],
	'installable': True,
	'application': True,
}
