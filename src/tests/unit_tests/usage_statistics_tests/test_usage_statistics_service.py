import pytest
from unittest.mock import AsyncMock, MagicMock

from quickapp.common.deployment_usage import DeploymentUsage
# noinspection PyProtectedMember
from quickapp.usage_statistics._pricing import _Pricing
from quickapp.usage_statistics.usage_statistics_service import UsageStatisticsService


@pytest.fixture
def mock_choice():
    choice = MagicMock()
    stage = MagicMock()
    choice.create_stage.return_value.__enter__.return_value = stage
    return choice


@pytest.fixture
def mock_pricing_service():
    pricing_service = AsyncMock()
    return pricing_service


@pytest.fixture
def service(mock_choice, mock_pricing_service):
    return UsageStatisticsService(mock_pricing_service, mock_choice)


@pytest.mark.asyncio
async def test_process_usage_statistics_empty_list(service, mock_choice):
    with patch("quickapp.usage_statistics.usage_statistics_service._UsageStatisticsRenderer") as mock_renderer:
        await service.process_usage_statistics([])

        mock_renderer.render_usage_statistics_table.assert_not_called()
        mock_choice.create_stage.assert_not_called()
        mock_choice.create_stage().__enter__().append_content.assert_not_called()


from unittest.mock import patch


@pytest.mark.asyncio
async def test_process_usage_statistics_single_deployment(service, mock_pricing_service, mock_choice):
    # Setup
    usage = DeploymentUsage(
        deployment_id="deploy1",
        deployment_name="Model A",
        model_name="gpt-4",
        prompt_tokens=100,
        completion_tokens=50
    )
    mock_pricing_service.get_price.return_value = _Pricing(0.01, 0.02)

    # Mock the renderer
    with patch("quickapp.usage_statistics.usage_statistics_service._UsageStatisticsRenderer") as mock_renderer:
        # Execute
        await service.process_usage_statistics([usage])

        # Verify service calls
        mock_pricing_service.get_price.assert_called_once_with("gpt-4")
        mock_choice.create_stage.assert_called_once_with("Usage Statistics")

        # Verify renderer call with aggregated values
        mock_renderer.render_usage_statistics_table.assert_called_once()
        args = mock_renderer.render_usage_statistics_table.call_args[0][0]
        assert len(args) == 1
        assert args[0].deployment_name == "Model A"
        assert args[0].deployment_id == "deploy1"
        assert args[0].total_prompt_tokens == "-"
        assert args[0].total_completion_tokens == "-"
        assert args[0].total_cost == 2.0  #


@pytest.mark.asyncio
async def test_process_usage_statistics_orchestrator(service, mock_pricing_service, mock_choice):
    # Setup
    usage = DeploymentUsage(
        prompt_tokens=100,
        completion_tokens=50,
        model_name="gpt-4"
    )
    mock_pricing_service.get_price.return_value = _Pricing(0.01, 0.02)

    # Mock the renderer
    with patch("quickapp.usage_statistics.usage_statistics_service._UsageStatisticsRenderer") as mock_renderer:
        # Execute
        await service.process_usage_statistics([usage])

        # Verify service calls
        mock_pricing_service.get_price.assert_called_once_with("gpt-4")
        mock_choice.create_stage.assert_called_once_with("Usage Statistics")

        # Verify renderer call with aggregated values
        mock_renderer.render_usage_statistics_table.assert_called_once()
        args = mock_renderer.render_usage_statistics_table.call_args[0][0]
        assert len(args) == 1
        assert args[0].deployment_name == "Orchestrator"
        assert args[0].deployment_id == "gpt-4"
        assert args[0].total_prompt_tokens == 100
        assert args[0].total_completion_tokens == 50
        assert args[0].total_cost == 2.0  # 0.01*100 + 0.02*50


@pytest.mark.asyncio
async def test_process_usage_statistics_multiple_deployments(service, mock_pricing_service, mock_choice):
    # Setup
    usages = [
        DeploymentUsage(  # Orchestrator
            deployment_id="Orchestrator",
            deployment_name="Orchestrator",
            model_name="gpt-4",
            prompt_tokens=100,
            completion_tokens=50
        ),
        DeploymentUsage(  # Orchestrator
            deployment_id="Orchestrator",
            deployment_name="Orchestrator",
            model_name="gpt-4",
            prompt_tokens=50,
            completion_tokens=25
        ),
        DeploymentUsage(  # Model 1
            deployment_id="deploy1",
            deployment_name="Model A",
            model_name="gpt-4-mini",
            prompt_tokens=1000,
            completion_tokens=1000
        ),
        DeploymentUsage(  # Another instance of Model 1
            deployment_id="deploy2",
            deployment_name="Model A",
            model_name="gpt-4-mini",
            prompt_tokens=100,
            completion_tokens=100
        )
    ]

    # Mock pricing service to return different values for different models
    async def get_price_side_effect(model_name):
        if model_name == "gpt-4":
            return _Pricing(0.01, 0.02)
        if model_name == "gpt-4-mini":
            return _Pricing(0.003, 0.004)
        return _Pricing("-", "-")

    mock_pricing_service.get_price.side_effect = get_price_side_effect

    # Mock the renderer
    with patch("quickapp.usage_statistics.usage_statistics_service._UsageStatisticsRenderer") as mock_renderer:
        # Execute
        await service.process_usage_statistics(usages)

        # Verify service calls
        assert mock_pricing_service.get_price.call_count == 4
        mock_choice.create_stage.assert_called_once_with("Usage Statistics")

        # Verify renderer call with aggregated values
        mock_renderer.render_usage_statistics_table.assert_called_once()
        args = mock_renderer.render_usage_statistics_table.call_args[0][0]
        assert len(args) == 2  # Two entries: orchestrator and Model A

        # Find and verify orchestrator entry
        orchestrator = next(a for a in args if a.deployment_name == "Orchestrator")
        assert orchestrator.deployment_name == "Orchestrator"
        assert orchestrator.deployment_id == "gpt-4"
        assert orchestrator.total_prompt_tokens == 150
        assert orchestrator.total_completion_tokens == 75
        assert orchestrator.total_cost == 3.0

        # Find and verify Model A entry (combined from 2 instances)
        model_a = next(a for a in args if a.deployment_name == "Model A")
        assert model_a.deployment_id in ["deploy1", "deploy2"]
        assert model_a.total_prompt_tokens == "-"  # Not tracked for deployments
        assert model_a.total_completion_tokens == "-"  # Not tracked for deployments
        assert model_a.total_cost == 7.7

@pytest.mark.asyncio
async def test_process_usage_statistics_no_price_for_model(service, mock_pricing_service, mock_choice):
    # Setup
    usage = DeploymentUsage(
        deployment_id="deploy1",
        deployment_name="Model A",
        model_name="unknown-model",
        prompt_tokens=100,
        completion_tokens=50
    )

    mock_pricing_service.get_price.return_value = _Pricing("-", "-")

    # Mock the renderer
    with patch("quickapp.usage_statistics.usage_statistics_service._UsageStatisticsRenderer") as mock_renderer:
        # Execute
        await service.process_usage_statistics([usage])

        # Verify service calls
        mock_pricing_service.get_price.assert_called_once_with("unknown-model")
        mock_choice.create_stage.assert_called_once_with("Usage Statistics")

        # Verify renderer call with aggregated values
        mock_renderer.render_usage_statistics_table.assert_called_once()
        args = mock_renderer.render_usage_statistics_table.call_args[0][0]
        assert len(args) == 1
        assert args[0].deployment_name == "Model A"
        assert args[0].deployment_id == "deploy1"
        assert args[0].total_prompt_tokens == "-"
        assert args[0].total_completion_tokens == "-"
        assert args[0].total_cost == "-"