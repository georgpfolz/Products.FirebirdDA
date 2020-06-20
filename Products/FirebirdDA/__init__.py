##############################################################################
#
# Copyright (c) 2001 Zope Corporation and Contributors. All Rights Reserved.
#
# This software is subject to the provisions of the Zope Public License,
# Version 2.0 (ZPL).  A copy of the ZPL should accompany this distribution.
# THIS SOFTWARE IS PROVIDED "AS IS" AND ANY AND ALL EXPRESS OR IMPLIED
# WARRANTIES ARE DISCLAIMED, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF TITLE, MERCHANTABILITY, AGAINST INFRINGEMENT, AND FITNESS
# FOR A PARTICULAR PURPOSE
#
##############################################################################
from . import DA

def manage_addFirebirdConnectionForm(self, REQUEST, *args, **kw):
    " "
    return DA.addConnectionForm(
        self, self, REQUEST,
        database_type=database_type)

def manage_addFirebirdConnection(
    self, id, title, connection, check=None, REQUEST=None):
    " "
    return DA.manage_addFirebirdConnection(
        self, id, title, connection, check, REQUEST)

def initialize(context):

    context.registerClass(
        DA.Connection,
        permission='Add Firebird Database Connections',
        constructors=(DA.manage_addFirebirdConnectionForm,
                      DA.manage_addFirebirdConnection)
    )
