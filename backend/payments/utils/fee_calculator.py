from decimal import Decimal, ROUND_HALF_UP

def get_default_method_fees():
    """
    Fallback default method fees if not configured.
    """
    return {
        "card": {
            "enabled": True,
            "stripe_baseline_pct": 2.9,
            "stripe_baseline_fixed": 0.30,
            "admin_markup_pct": 1.1,
            "total_pct": 4.0,
            "total_fixed": 0.30,
            "label": "Credit/Debit Card"
        },
        "us_bank_account": {
            "enabled": True,
            "stripe_baseline_pct": 0.8,
            "stripe_baseline_fixed": 0.0,
            "stripe_cap_usd": 5.0,
            "admin_markup_pct": 0.2,
            "total_pct": 1.0,
            "total_fixed": 0.0,
            "label": "Bank Transfer (ACH)"
        },
        "klarna": {
            "enabled": True,
            "stripe_baseline_pct": 5.99,
            "stripe_baseline_fixed": 0.30,
            "admin_markup_pct": 0.0,
            "total_pct": 5.99,
            "total_fixed": 0.30,
            "label": "Klarna (Buy Now, Pay Later)"
        }
    }

def calculate_fee(base_amount: Decimal, method_type: str, settings: dict) -> dict:
    """
    Calculates the administrative fee based on the payment method and gateway settings.
    
    Args:
        base_amount: Decimal, the base invoice amount to charge.
        method_type: str, the stripe payment method type (e.g., 'card', 'us_bank_account').
        settings: dict, the PaymentGateway.settings JSON field.
        
    Returns:
        dict containing fee breakdown and total charge.
    """
    if not isinstance(base_amount, Decimal):
        base_amount = Decimal(str(base_amount))

    fee_payer = settings.get("fee_payer", "resident")
    platform_fee_enabled = settings.get("platform_fee_enabled", True)
    
    method_fees = settings.get("method_fees", get_default_method_fees())
    
    # Fallback to card config if method_type is not explicitly defined in settings
    defaults = get_default_method_fees()
    if method_type == "us_bank_account":
        config = method_fees.get("us_bank_account", method_fees.get("ach", defaults["us_bank_account"]))
    elif method_type == "klarna":
        config = method_fees.get("klarna", defaults["klarna"])
    else:
        config = method_fees.get(method_type, method_fees.get("card", defaults["card"]))

    if not platform_fee_enabled or fee_payer == "HOA":
        # Resident doesn't pay any fee, HOA absorbs it
        # We might still want to estimate stripe cost for internal reporting, but resident fee is 0
        fee_amount = Decimal("0.00")
        total_charge = base_amount
        stripe_baseline_cost = Decimal("0.00")
        if "stripe_baseline_pct" in config:
             stripe_baseline_cost = (base_amount * Decimal(str(config.get("stripe_baseline_pct", 0))) / Decimal("100")) + Decimal(str(config.get("stripe_baseline_fixed", 0)))
             if "stripe_cap_usd" in config and stripe_baseline_cost > Decimal(str(config["stripe_cap_usd"])):
                 stripe_baseline_cost = Decimal(str(config["stripe_cap_usd"]))

        return {
            "base_amount": float(base_amount),
            "fee_pct": 0.0,
            "fee_fixed": 0.0,
            "fee_amount": 0.0,
            "total_charge": float(total_charge),
            "method_type": method_type,
            "fee_label": "Fee covered by HOA",
            "fee_payer": "HOA",
            "stripe_baseline_cost": float(stripe_baseline_cost.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
            "admin_profit_estimate": float(-stripe_baseline_cost) # HOA loses money
        }

    # Calculate fee to charge the resident
    # SystemSettings saves 'amount' instead of 'total_pct', and 'flat_fee' instead of 'total_fixed'
    total_pct = Decimal(str(config.get("total_pct", config.get("amount", 0))))
    total_fixed = Decimal(str(config.get("total_fixed", config.get("flat_fee", 0))))
    
    # Check type if SystemSettings passed it
    fee_type = config.get("type", "percentage")
    if fee_type == "flat":
        # If type is explicitly 'flat', then 'amount' is actually fixed, not percentage
        total_fixed = Decimal(str(config.get("amount", 0))) + Decimal(str(config.get("flat_fee", 0)))
        total_pct = Decimal("0")
        
    # Note: If fee is added on top, mathematically the fee is (base_amount * total_pct) + total_fixed
    # Some platforms use (base_amount + total_fixed) / (1 - total_pct) to guarantee exactly base_amount net,
    # but the standard "add-on" model usually just adds the percentage of the base.
    fee_amount = (base_amount * total_pct / Decimal("100")) + total_fixed
    
    # Enforce ACH (us_bank_account) cap dynamically if present
    stripe_cap = config.get("stripe_cap_usd")
    if method_type == "us_bank_account" and stripe_cap is not None:
        # Assuming admin markup also respects a cap or we cap the total.
        # Standard approach: If stripe has a $5 cap, and we charge 1%, we might cap the total fee at $5 + markup.
        # For simplicity, if cap is $5 and our markup is 0.2%, let's say we cap the total fee to (stripe_cap + (base_amount * markup)).
        # Let's read admin_markup_pct to calculate profit
        stripe_baseline_cost = (base_amount * Decimal(str(config.get("stripe_baseline_pct", 0))) / Decimal("100")) + Decimal(str(config.get("stripe_baseline_fixed", 0)))
        if stripe_baseline_cost > Decimal(str(stripe_cap)):
            stripe_baseline_cost = Decimal(str(stripe_cap))
            
        admin_markup_pct = Decimal(str(config.get("admin_markup_pct", 0)))
        admin_profit_estimate = (base_amount * admin_markup_pct / Decimal("100"))
        
        # New capped fee
        fee_amount = stripe_baseline_cost + admin_profit_estimate
    else:
        # Calculate expected stripe cost for profit estimation
        stripe_baseline_cost = (base_amount * Decimal(str(config.get("stripe_baseline_pct", 0))) / Decimal("100")) + Decimal(str(config.get("stripe_baseline_fixed", 0)))
        admin_profit_estimate = fee_amount - stripe_baseline_cost

    fee_amount = fee_amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    total_charge = base_amount + fee_amount
    
    label = config.get("label", method_type.replace('_', ' ').title())
    fee_label = f"{label} Fee"
    if total_pct > 0 and total_fixed > 0:
        fee_label += f" ({total_pct}% + ${total_fixed})"
    elif total_pct > 0:
        fee_label += f" ({total_pct}%)"
    elif total_fixed > 0:
        fee_label += f" (${total_fixed})"

    return {
        "base_amount": float(base_amount),
        "fee_pct": float(total_pct),
        "fee_fixed": float(total_fixed),
        "fee_amount": float(fee_amount),
        "total_charge": float(total_charge),
        "method_type": method_type,
        "fee_label": fee_label,
        "fee_payer": "RESIDENT",
        "stripe_baseline_cost": float(stripe_baseline_cost.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        "admin_profit_estimate": float(admin_profit_estimate.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
    }
