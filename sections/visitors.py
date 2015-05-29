# -*- coding: utf-8 -*-

from hashlib import sha1

from aweber_api import AWeberAPI
from Crypto.Cipher import AES
from flask import abort, Blueprint, g, redirect, request, url_for
from rollbar import report_exc_info
from ujson import loads

from modules import models

from settings import AWEBER, CLICKBANK

blueprint = Blueprint('visitors', __name__)


@blueprint.route('/')
def dashboard():
    return redirect(url_for('administrators.dashboard'))


@blueprint.route('/notify', methods=['POST'])
def notify():
    message = loads(request.data)
    algorithm = sha1()
    algorithm.update(CLICKBANK)
    dictionary = loads(''.join([
        character
        for character in AES.new(
            algorithm.hexdigest()[:32], AES.MODE_CBC, message['iv'].decode('base64')
        ).decrypt(
            message['notification'].decode('base64')
        ).strip()
        if ord(character) >= 32
    ]))
    billing = {}
    try:
        billing = dictionary['customer']['billing']
    except KeyError:
        pass
    email = billing.get('email', '')
    if not email:
        abort(500)
    name = billing.get('fullName', '')
    customer = g.mysql.query(models.customer).filter(models.customer.email == email).first()
    if not customer:
        customer = models.customer(**{
            'address': billing.get('address', ''),
            'email': email,
            'password': '',
            'name': name,
            'phone_number': billing.get('phoneNumber', ''),
            'status': 'On',
        })
        aweber = AWeberAPI(
            AWEBER['consumer_key'], AWEBER['consumer_secret'],
        ).get_account(
            AWEBER['access_key'], AWEBER['access_secret'],
        )
        try:
            aweber.load_from_url('/accounts/%(account_id)s/lists/%(list_id)s' % {
                'account_id': AWEBER['account_id'],
                'list_id': AWEBER['list_id'],
            }).subscribers.create(**{
                'email': email,
                'name': name,
            })
        except Exception:
            report_exc_info()
            pass
    type = dictionary.get('transactionType', '')
    if type == 'SALE':
        customer.status = 'On'
    if type == 'RFND':
        customer.status = 'Off'
    if type == 'CGBK':
        customer.status = 'Off'
    if type == 'FEE':
        customer.status = 'On'
    if type == 'BILL':
        customer.status = 'On'
    if type == 'TEST_SALE':
        customer.status = 'On'
    if type == 'TEST_BILL':
        customer.status = 'On'
    if type == 'TEST_RFND':
        customer.status = 'Off'
    if type == 'TEST_FEE':
        customer.status = 'On'
    g.mysql.add(customer)
    order = models.order(**{
        'affiliate': dictionary.get('affiliate', ''),
        'amounts_account': dictionary.get('totalAccountAmount', 0.00),
        'amounts_order': dictionary.get('totalOrderAmount', 0.00),
        'amounts_shipping': dictionary.get('totalShippingAmount', 0.00),
        'amounts_tax': dictionary.get('totalTaxAmount', 0.00),
        'currency': dictionary.get('currency', ''),
        'customer': customer,
        'language': dictionary.get('orderLanguage', ''),
        'payment_method': dictionary.get('paymentMethod', ''),
        'receipt': dictionary.get('receipt', ''),
        'role': dictionary.get('role', ''),
        'timestamp': dictionary.get('transactionTime', ''),
        'tracking_codes': dictionary.get('trackingCodes', []),
        'type': type,
        'vendor': dictionary.get('vendor', ''),
        'vendor_variables': dictionary.get('vendorVariables', {}),
    })
    g.mysql.add(order)
    for item in dictionary.get('lineItems', []):
        g.mysql.add(models.order_product(**{
            'amount': item.get('accountAmount', 0.00),
            'item_number': item.get('itemNo', ''),
            'order': order,
            'recurring': item.get('recurring', ''),
            'shippable': item.get('shippable', ''),
            'title': item.get('productTitle', ''),
            'url': item.get('downloadUrl', ''),
        }))
    g.mysql.commit()
    return ('', 204)
