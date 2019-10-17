# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import api, fields, models

class StockPicking(models.Model):
	_inherit = 'stock.picking'

	s_inv = fields.Many2one('account.invoice', "Invoice")
	
class StockMove(models.Model):
	_inherit = 'stock.move'
	
	account_line_id = fields.Many2one('account.invoice.line', 'Invoice Line')
	
	

