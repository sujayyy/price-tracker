from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.config import get_settings
from app.core.security import require_internal_secret
from app.schemas.decision import RunOut
from app.schemas.demo import DemoClearOut, DemoPriceIn, DemoPriceOut
from app.services import demo
from app.services.runner import run_once

router = APIRouter(prefix="/internal", tags=["internal"], dependencies=[Depends(require_internal_secret)])


@router.post("/run-once", response_model=RunOut)
def trigger_run(force: bool = False):
    """One scheduler cycle. `force=true` checks every active item regardless of its interval."""
    s = run_once(force=force)
    return RunOut(
        run_id=s.run_id,
        items_checked=s.items_checked,
        agent_invocations=s.agent_invocations,
        errors=s.errors,
        alerts_sent=s.alerts_sent,
        triggers=s.triggers,
    )


def require_demo_enabled() -> None:
    if not get_settings().demo_endpoints_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Demo endpoints are disabled (set DEMO_ENDPOINTS_ENABLED=true)")


@router.post("/demo/price", response_model=DemoPriceOut, dependencies=[Depends(require_demo_enabled)])
def simulate_price(body: DemoPriceIn):
    """Simulate one competitor listing's price, then run the normal pipeline for its product.

    Only the scraper's output is replaced. The reading is stored (tagged source='demo') and goes
    through the same rules, repricing workflow, proposal and ops email as a real fetch.
    """
    try:
        return demo.simulate_price(body.listing_id, body.price_inr, body.in_stock)
    except demo.ItemNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except demo.ItemPaused as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.delete("/demo/price", response_model=DemoClearOut, dependencies=[Depends(require_demo_enabled)])
def clear_simulated_prices(product_id: int = Query(gt=0)):
    """Delete the simulated readings of a product's listings. Real readings, decisions and alerts are kept."""
    try:
        return DemoClearOut(product_id=product_id, deleted_observations=demo.clear_simulated_prices(product_id))
    except demo.ItemNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
