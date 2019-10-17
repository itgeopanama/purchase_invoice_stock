# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import fields, models, api, _
import logging
from odoo.exceptions import AccessError, UserError, RedirectWarning, ValidationError, Warning
from odoo.tools import float_is_zero, float_compare

_logger = logging.getLogger(__name__)
	
class AccountInvoice(models.Model):
	_inherit='account.invoice'
		
	@api.model
	def _default_warehouse_id(self):
		company = self.env.user.company_id.id
		warehouse_ids = self.env['stock.warehouse'].search([('company_id', '=', company)], limit=1)
		return warehouse_ids
		
	@api.model
	def _default_picking_type(self):
		picking_type = self.env['stock.picking.type'].search([('code', '=', 'incoming')], limit=1)
		return picking_type
			
	picking_policy = fields.Selection([
		('direct', 'Deliver each product when available'),
		('one', 'Deliver all products at once')],
		string='Shipping Policy', required=True, readonly=True, default='direct',
		states={'draft': [('readonly', False)], 'sent': [('readonly', False)]})
	picking_type_id = fields.Many2one('stock.picking.type', 'Deliver To', states={'draft': [('readonly', False)]}, required=True, default=_default_picking_type,\
		help="This will determine picking type of incoming shipment", domain=[('code', '=', 'incoming')])
	default_location_dest_id_usage = fields.Selection(related='picking_type_id.default_location_dest_id.usage', string='Destination Location Type',\
		help="Technical field used to display the Drop Ship Address", readonly=True)
	warehouse_id = fields.Many2one(
		'stock.warehouse', string='Warehouse',
		required=True, readonly=True, states={'draft': [('readonly', False)]},
		default=_default_warehouse_id)
	picking_ids = fields.Many2many('stock.picking', compute='_compute_picking_ids', string='Picking associated to this invoice')
	delivery_count = fields.Integer(string='Delivery Orders', compute='_compute_picking_ids')
	create_stock = fields.Boolean(default=False)
	pricelist_id = fields.Many2one('product.pricelist', string='Pricelist', required=True, readonly=True, states={'draft': [('readonly', False)]}, help="Pricelist for current invoices")
	
	@api.multi
	@api.depends()
	def _compute_picking_ids(self):
		for order in self:
			order.picking_ids = self.env['stock.picking'].search([('s_inv', '=', order.id)])
			order.delivery_count = len(order.picking_ids)
	
	@api.onchange('warehouse_id')
	def _onchange_warehouse_id(self):
		if self.warehouse_id.company_id:
			self.company_id = self.warehouse_id.company_id.id
			
	@api.multi
	def action_view_delivery(self):
		'''
		This function returns an action that display existing delivery orders
		of given sales order ids. It can either be a in a list or in a form
		view, if there is only one delivery order to show.
		'''
		action = self.env.ref('stock.action_picking_tree_all').read()[0]

		pickings = self.mapped('picking_ids')
		if len(pickings) > 1:
			action['domain'] = [('id', 'in', pickings.ids)]
		elif pickings:
			action['views'] = [(self.env.ref('stock.view_picking_form').id, 'form')]
			action['res_id'] = pickings.id
		return action
	
	@api.multi
	def action_invoice_open(self):
		res = super(AccountInvoice, self).action_invoice_open()
		if self.type == 'in_invoice':
			to_stock_invoices = self.filtered(lambda inv: inv.create_stock == True)
			to_stock_invoices.action_create_picking()
			pickings = self.mapped('picking_ids')
			if pickings:
				trans = self.env['stock.immediate.transfer'].create({
					'pick_id': pickings[0].id
				})
				#trans.process()
		return res
		
	@api.multi
	def action_create_picking(self):
		StockPicking = self.env['stock.picking']
		for order in self:
			if any([ptype in ['product', 'consu'] for ptype in order.invoice_line_ids.mapped('product_id.type')]):
				pickings = order.picking_ids.filtered(lambda x: x.state not in ('done','cancel'))
				if not pickings:
					res = order._prepare_picking()
					picking = StockPicking.create(res)
				else:
					picking = pickings[0]
					
				moves = order.invoice_line_ids._create_stock_moves(picking)
				moves = moves.filtered(lambda x: x.state not in ('done', 'cancel'))
				#moves = moves.filtered(lambda x: x.state not in ('done', 'cancel')).action_confirm()
				seq = 0
				for move in sorted(moves, key=lambda move: move.date_expected):
					seq += 5
					move.sequence = seq
				#moves.force_assign()
				picking.message_post_with_view('mail.message_origin_link',
					values={'self': picking, 'origin': order},
					subtype_id=self.env.ref('mail.mt_note').id)
		return True
				
	@api.multi
	def _get_destination_location(self):
		self.ensure_one()
		return self.picking_type_id.default_location_dest_id.id
		
	@api.model
	def _prepare_picking(self):
		if not self.partner_id.property_stock_supplier.id:
			raise UserError(_("You must set a Vendor Location for this partner %s") % self.partner_id.name)
		return {
			'picking_type_id': self.picking_type_id.id,
			'partner_id': self.partner_id.id,
			'date': self.date_invoice,
			'origin': self.name,
			'location_dest_id': self._get_destination_location(),
			'location_id': self.partner_id.property_stock_supplier.id,
			'company_id': self.company_id.id,
			's_inv': self.id
		}
		
	@api.multi
	@api.onchange('partner_id')
	def onchange_partner_id_pricelist(self):
		"""
		Update the following fields when the partner is changed:
		- Pricelist
		"""
		
		values = {
			'pricelist_id': self.partner_id.property_product_pricelist and self.partner_id.property_product_pricelist.id or False,
		}
		self.update(values)
		
class AccountInvoiceLine(models.Model):
	_inherit="account.invoice.line"
	
	move_ids = fields.One2many('stock.move', 'account_line_id', string='Reservation', readonly=True, ondelete='set null', copy=False)
	
	@api.multi
	def _get_stock_move_price_unit(self):
		self.ensure_one()
		line = self[0]
		order = line.invoice_id
		price_unit = line.price_unit
		if line.invoice_line_tax_ids:
			price_unit = line.invoice_line_tax_ids.with_context(round=False).compute_all(
				price_unit, currency=line.invoice_id.currency_id, quantity=1.0, product=line.product_id, partner=line.invoice_id.partner_id
			)['total_excluded']
		if line.uom_id.id != line.product_id.uom_id.id:
			price_unit *= line.uom_id.factor / line.product_id.uom_id.factor
		if order.currency_id != order.company_id.currency_id:
			price_unit = order.currency_id.compute(price_unit, order.company_id.currency_id, round=False)
		return price_unit
		
	@api.multi
	def _create_stock_moves(self, picking):
		moves = self.env['stock.move']
		done = self.env['stock.move'].browse()
		for line in self:
			for val in line._prepare_stock_moves(picking):
				done += moves.create(val)
		return done
		
	@api.multi
	def _prepare_stock_moves(self, picking):
		""" Prepare the stock moves data for one order line. This function returns a list of
		dictionary ready to be used in stock.move's create()
		"""
		self.ensure_one()
		res = []
		if self.product_id.type not in ['product', 'consu']:
			return res
		qty = 0.0
		price_unit = self._get_stock_move_price_unit()
		for move in self.move_ids.filtered(lambda x: x.state != 'cancel'):
			qty += move.product_qty
		template = {
			'name': self.name or '',
			'product_id': self.product_id.id,
			'product_uom': self.uom_id.id,
			'date': self.invoice_id.date_invoice,
			'date_expected': self.invoice_id.date_invoice,
			'location_id': self.invoice_id.partner_id.property_stock_supplier.id,
			'location_dest_id': self.invoice_id._get_destination_location(),
			'picking_id': picking.id,
			'partner_id': self.invoice_id.partner_id.id,
			'move_dest_id': False,
			'state': 'draft',
			'invoice_line_id': self.id,
			'company_id': self.invoice_id.company_id.id,
			'price_unit': price_unit,
			'picking_type_id': self.invoice_id.picking_type_id.id,
			'procurement_id': False,
			'origin': self.invoice_id.number,
			'route_ids': self.invoice_id.picking_type_id.warehouse_id and [(6, 0, [x.id for x in self.invoice_id.picking_type_id.warehouse_id.route_ids])] or [],
			'warehouse_id': self.invoice_id.picking_type_id.warehouse_id.id,
		}
		# Fullfill all related procurements with this po line
		diff_quantity = self.quantity - qty
		
		if float_compare(diff_quantity, 0.0,  precision_rounding=self.uom_id.rounding) > 0:
			template['product_uom_qty'] = diff_quantity
			res.append(template)
		return res