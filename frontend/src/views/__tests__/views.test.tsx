import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ComponentType } from 'react';
import { beforeEach, describe, expect, it } from 'vitest';

import { AlarmsView } from '../AlarmsView';
import { BMSView } from '../BMSView';
import { BatterySystemsView } from '../BatterySystemsView';
import { ConfigurationView } from '../ConfigurationView';
import { EMSView } from '../EMSView';
import { EquipmentControllerView } from '../EquipmentControllerView';
import { EquipmentLibraryView } from '../EquipmentLibraryView';
import { GridPOIView } from '../GridPOIView';
import { GridServicesView } from '../GridServicesView';
import { HistorianView } from '../HistorianView';
import { PCSView } from '../PCSView';
import { PPCView } from '../PPCView';
import { PlantOverviewView } from '../PlantOverviewView';
import { PluginManagerView } from '../PluginManagerView';
import { ScenarioManagerView } from '../ScenarioManagerView';
import { SimulationView } from '../SimulationView';
import { SingleLineDiagramView } from '../SingleLineDiagramView';
import { SystemSettingsView } from '../SystemSettingsView';
import { TransformersSwitchgearView } from '../TransformersSwitchgearView';
import { WarrantyMetricsView } from '../WarrantyMetricsView';

import {
  CONNECTED_TELEMETRY,
  DISCONNECTED_TELEMETRY,
  HEALTHY_SYSTEM_INFO,
} from '../../test/fixtures';
import { bodyOf, installFetchMock, jsonResponse } from '../../test/fetchMock';

/**
 * Every view of the HMI, with the heading it has to present.
 *
 * The list is the contract: a view that is added without being listed here
 * loses the banner check below, and a view that is renamed loses the heading
 * check. Both failures are the point of the table.
 */
const VIEWS: { heading: string; Component: ComponentType }[] = [
  { heading: 'Plant Overview', Component: PlantOverviewView },
  { heading: 'Electrical Single-Line Diagram (SLD)', Component: SingleLineDiagramView },
  { heading: 'Battery Systems', Component: BatterySystemsView },
  { heading: 'Master BMS Controller', Component: BMSView },
  { heading: 'PCS / Inverters', Component: PCSView },
  { heading: 'Transformers & Switchgear', Component: TransformersSwitchgearView },
  { heading: 'Grid & POI', Component: GridPOIView },
  { heading: 'Equipment Controller (Layer A)', Component: EquipmentControllerView },
  { heading: 'Power Plant Controller (PPC - Layer B)', Component: PPCView },
  { heading: 'Energy Management System (EMS - Layer C)', Component: EMSView },
  { heading: 'Grid Services', Component: GridServicesView },
  { heading: 'Alarms & Events', Component: AlarmsView },
  { heading: 'Historian', Component: HistorianView },
  { heading: 'Warranty Metrics', Component: WarrantyMetricsView },
  { heading: 'Simulation Control', Component: SimulationView },
  { heading: 'Scenario Manager', Component: ScenarioManagerView },
  { heading: 'Equipment Library', Component: EquipmentLibraryView },
  { heading: 'Plugin Manager', Component: PluginManagerView },
  { heading: 'System Settings', Component: SystemSettingsView },
  { heading: 'Plant Configuration', Component: ConfigurationView },
];

/**
 * The mock backend every view sees.
 *
 * The install sits at the top level of the file on purpose: a `beforeEach`
 * inside one `describe` would leave the sibling describes — the ones that
 * assert on live telemetry — with no backend at all, and they would fail on
 * a network error rather than on the behaviour they are about.
 */
beforeEach(() => {
  installFetchMock({
    '/api/v1/overview': () => jsonResponse(CONNECTED_TELEMETRY),
    '/api/v1/info': () => jsonResponse(HEALTHY_SYSTEM_INFO),
    '/api/v1/simulation/control': () =>
      jsonResponse({
        status: 'SUCCESS',
        engine_state: 'PAUSED',
        message: 'The engine is paused.',
      }),
  });
});

describe('HMI Views', () => {
  describe.each(VIEWS)('$heading', ({ heading, Component }) => {
    it('presents its heading', () => {
      render(<Component />);

      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent(heading);
    });

    it('labels its figures as simulated data', () => {
      render(<Component />);

      expect(screen.getByText(/SIMULATED DATA ONLY/)).toBeInTheDocument();
    });
  });
});

describe('Plant Overview View', () => {
  it('shows the plant power the simulation reports', async () => {
    render(<PlantOverviewView />);

    await waitFor(() => expect(screen.getByText('4.25 MW')).toBeInTheDocument());
    expect(screen.getByText('1.50 MVAR')).toBeInTheDocument();
    expect(screen.getByText('-5.0 / +5.0 MW')).toBeInTheDocument();
  });

  it('shows the stored energy and state of charge', async () => {
    render(<PlantOverviewView />);

    await waitFor(() => expect(screen.getByText('63.5 % (12.8 MWh)')).toBeInTheDocument());
  });

  it('shows the grid frequency and the point-of-interconnection voltage', async () => {
    render(<PlantOverviewView />);

    await waitFor(() => expect(screen.getByText('50.00 Hz | 33.00 kV')).toBeInTheDocument());
  });

  it('shows the simulation clock and the wall clock separately', async () => {
    render(<PlantOverviewView />);

    await waitFor(() => expect(screen.getByText('00:01:23.450.000')).toBeInTheDocument());
    expect(screen.getByText('09:15:42')).toBeInTheDocument();
  });

  it('reports that the plant is not connected when the engine is absent', async () => {
    installFetchMock({
      '/api/v1/overview': () => jsonResponse(DISCONNECTED_TELEMETRY),
    });

    render(<PlantOverviewView />);

    await waitFor(() => expect(screen.getByText('NOT CONNECTED')).toBeInTheDocument());
    expect(screen.queryByText('4.25 MW')).not.toBeInTheDocument();
  });
});

describe('Battery Systems View', () => {
  it('shows a container card per container of the reference plant', async () => {
    render(<BatterySystemsView />);

    await waitFor(() => expect(screen.getAllByText('63.5 % SoC')).toHaveLength(4));
    expect(screen.getByText('Container 01')).toBeInTheDocument();
    expect(screen.getByText('Container 04')).toBeInTheDocument();
  });
});

describe('PCS View', () => {
  it('separates the requested, accepted, actual and measured setpoints', async () => {
    render(<PCSView />);

    await waitFor(() => expect(screen.getByText('1. REQUESTED')).toBeInTheDocument());
    expect(screen.getByText('2. ACCEPTED')).toBeInTheDocument();
    expect(screen.getByText('3. ACTUAL')).toBeInTheDocument();
    expect(screen.getByText('4. MEASURED')).toBeInTheDocument();
  });
});

describe('Grid and POI View', () => {
  it('shows the direction of the flow at the point of interconnection', async () => {
    render(<GridPOIView />);

    await waitFor(() => expect(screen.getByText('EXPORTING (+P)')).toBeInTheDocument());
    expect(screen.getByText('+4.25 MW Discharging')).toBeInTheDocument();
  });
});

describe('Alarms View', () => {
  it('reports that no alarm is active', async () => {
    render(<AlarmsView />);

    await waitFor(() => expect(screen.getByText('Active Alarms (0)')).toBeInTheDocument());
    expect(
      screen.getByText('No active faults or critical alarms recorded.'),
    ).toBeInTheDocument();
  });

  it('counts the active alarms the telemetry reports', async () => {
    installFetchMock({
      '/api/v1/overview': () => jsonResponse(DISCONNECTED_TELEMETRY),
    });

    render(<AlarmsView />);

    await waitFor(() => expect(screen.getByText('Active Alarms (3)')).toBeInTheDocument());
  });
});

describe('Single-Line Diagram View', () => {
  it('shows the equipment of the reference topology', () => {
    render(<SingleLineDiagramView />);

    expect(screen.getByText(/PCS Inverter 01-04/)).toBeInTheDocument();
    expect(screen.getByText(/Transformer 10MVA/)).toBeInTheDocument();
    expect(screen.getByText(/Breaker: CLOSED/)).toBeInTheDocument();
    expect(screen.getByText(/POI Boundary Meter/)).toBeInTheDocument();
    expect(screen.getByText(/50 Hz Utility Grid/)).toBeInTheDocument();
  });

  it('opens the drawer on the equipment the operator selects', async () => {
    const user = userEvent.setup();
    render(<SingleLineDiagramView />);

    expect(screen.getByRole('heading', { level: 3 })).toHaveTextContent('Container 01');

    await user.click(screen.getByText(/PCS Inverter 01-04/));

    expect(screen.getByRole('heading', { level: 3 })).toHaveTextContent('PCS Inverter 01-04');
  });

  it('reports the ratings of the equipment the operator selects', async () => {
    const user = userEvent.setup();
    render(<SingleLineDiagramView />);

    await user.click(screen.getByText(/Transformer 10MVA/));
    expect(screen.getByText('690V / 13.8kV')).toBeInTheDocument();
    expect(screen.getByText('4.86 MW')).toBeInTheDocument();
    // A transformer carries no state of charge, so the drawer omits it.
    expect(screen.queryByText(/Battery SoC:/)).not.toBeInTheDocument();

    await user.click(screen.getByText(/POI Boundary Meter/));
    expect(screen.getByRole('heading', { level: 3 })).toHaveTextContent('POI Boundary Meter');
    expect(screen.getByText('METER')).toBeInTheDocument();

    await user.click(screen.getByText(/50 Hz Utility Grid/));
    expect(screen.getByRole('heading', { level: 3 })).toHaveTextContent('50 Hz Utility Grid');
  });

  it('reports the state of charge of a container', async () => {
    const user = userEvent.setup();
    render(<SingleLineDiagramView />);

    await user.click(screen.getByText('Container 02'));

    expect(screen.getByRole('heading', { level: 3 })).toHaveTextContent('Container 02');
    expect(screen.getByText(/Battery SoC:/)).toBeInTheDocument();

    const drawer = screen.getByRole('heading', { level: 3 }).parentElement as HTMLElement;
    expect(drawer).toHaveTextContent('Battery SoC: 64%');
  });
});

describe('Simulation Control View', () => {
  it('shows the state of the simulation engine', async () => {
    render(<SimulationView />);

    await waitFor(() => expect(screen.getByText('RUNNING')).toBeInTheDocument());
  });

  it('asks for a confirmation before it acts on the engine', async () => {
    const user = userEvent.setup();
    render(<SimulationView />);

    await user.click(screen.getByRole('button', { name: 'PAUSE' }));

    expect(screen.getByText('Confirm Engine Control Action')).toBeInTheDocument();
    expect(
      screen.getByText('Are you sure you want to execute: Pause Engine?'),
    ).toBeInTheDocument();
  });

  it('dispatches the action once the operator confirms it', async () => {
    const mock = installFetchMock({
      '/api/v1/overview': () => jsonResponse(CONNECTED_TELEMETRY),
      '/api/v1/info': () => jsonResponse(HEALTHY_SYSTEM_INFO),
      '/api/v1/simulation/control': () =>
        jsonResponse({
          status: 'SUCCESS',
          engine_state: 'PAUSED',
          message: 'The engine is paused.',
        }),
    });
    const user = userEvent.setup();
    render(<SimulationView />);

    await user.click(screen.getByRole('button', { name: 'PAUSE' }));
    await user.click(screen.getByRole('button', { name: /CONFIRM & EXECUTE/ }));

    await waitFor(() => expect(screen.getByText(/The engine is paused\./)).toBeInTheDocument());

    const call = mock.callsTo('/api/v1/simulation/control')[0];
    expect(bodyOf(call)).toEqual({ action: 'PAUSE' });
  });

  it('dispatches nothing when the operator cancels', async () => {
    const mock = installFetchMock({
      '/api/v1/overview': () => jsonResponse(CONNECTED_TELEMETRY),
      '/api/v1/info': () => jsonResponse(HEALTHY_SYSTEM_INFO),
      '/api/v1/simulation/control': () => jsonResponse({ status: 'SUCCESS' }),
    });
    const user = userEvent.setup();
    render(<SimulationView />);

    await user.click(screen.getByRole('button', { name: 'PAUSE' }));
    await user.click(screen.getByRole('button', { name: /CANCEL/ }));

    expect(mock.callsTo('/api/v1/simulation/control')).toHaveLength(0);
  });

  it('dispatches a single step', async () => {
    const mock = installFetchMock({
      '/api/v1/overview': () => jsonResponse(CONNECTED_TELEMETRY),
      '/api/v1/info': () => jsonResponse(HEALTHY_SYSTEM_INFO),
      '/api/v1/simulation/control': () => jsonResponse({ status: 'SUCCESS' }),
    });
    const user = userEvent.setup();
    render(<SimulationView />);

    await user.click(screen.getByRole('button', { name: /SINGLE STEP/ }));
    expect(
      screen.getByText('Are you sure you want to execute: Single Step (+10ms)?'),
    ).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /CONFIRM & EXECUTE/ }));

    await waitFor(() => expect(mock.callsTo('/api/v1/simulation/control')).toHaveLength(1));
    expect(bodyOf(mock.callsTo('/api/v1/simulation/control')[0])).toEqual({ action: 'STEP' });
  });

  it('dispatches a reset of the simulation clock', async () => {
    const mock = installFetchMock({
      '/api/v1/overview': () => jsonResponse(CONNECTED_TELEMETRY),
      '/api/v1/info': () => jsonResponse(HEALTHY_SYSTEM_INFO),
      '/api/v1/simulation/control': () => jsonResponse({ status: 'SUCCESS' }),
    });
    const user = userEvent.setup();
    render(<SimulationView />);

    await user.click(screen.getByRole('button', { name: /RESET SIMULATION/ }));
    expect(
      screen.getByText('Are you sure you want to execute: Reset Simulation Clock?'),
    ).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /CONFIRM & EXECUTE/ }));

    await waitFor(() => expect(mock.callsTo('/api/v1/simulation/control')).toHaveLength(1));
    expect(bodyOf(mock.callsTo('/api/v1/simulation/control')[0])).toEqual({ action: 'RESET' });
  });

  it('offers a start and a stop for the engine lifecycle', async () => {
    const mock = installFetchMock({
      '/api/v1/overview': () => jsonResponse(CONNECTED_TELEMETRY),
      '/api/v1/info': () => jsonResponse(HEALTHY_SYSTEM_INFO),
      '/api/v1/simulation/control': () => jsonResponse({ status: 'SUCCESS' }),
    });
    const user = userEvent.setup();
    render(<SimulationView />);

    // Without a start and a stop the operator cannot begin or end a
    // continuous run from the screen at all.
    await user.click(screen.getByRole('button', { name: 'START' }));
    expect(
      screen.getByText('Are you sure you want to execute: Start Engine?'),
    ).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /CONFIRM & EXECUTE/ }));
    await waitFor(() => expect(mock.callsTo('/api/v1/simulation/control')).toHaveLength(1));
    expect(bodyOf(mock.callsTo('/api/v1/simulation/control')[0])).toEqual({ action: 'START' });

    await user.click(screen.getByRole('button', { name: 'STOP' }));
    expect(
      screen.getByText('Are you sure you want to execute: Stop Engine?'),
    ).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /CONFIRM & EXECUTE/ }));
    await waitFor(() => expect(mock.callsTo('/api/v1/simulation/control')).toHaveLength(2));
    expect(bodyOf(mock.callsTo('/api/v1/simulation/control')[1])).toEqual({ action: 'STOP' });
  });

  it('reports that the engine is not connected when the health check fails', async () => {
    installFetchMock({
      '/api/v1/overview': () => jsonResponse(CONNECTED_TELEMETRY),
      '/api/v1/info': () => jsonResponse({ detail: 'not ready' }, 503),
      '/api/v1/simulation/control': () => jsonResponse({ status: 'SUCCESS' }),
    });

    render(<SimulationView />);

    await waitFor(() => expect(screen.getByText('NOT_CONNECTED')).toBeInTheDocument());
  });

  it('shows the wall-clock speed factor the engine reports', async () => {
    render(<SimulationView />);

    // The card shows the factor in force, not a fixed value: the speed
    // factor was readable and settable through the API but the screen
    // displayed a constant that said nothing about the clock.
    await waitFor(() => expect(screen.getByText('1.0 x')).toBeInTheDocument());
  });

  it('dispatches a speed factor the operator asks for', async () => {
    const mock = installFetchMock({
      '/api/v1/overview': () => jsonResponse(CONNECTED_TELEMETRY),
      '/api/v1/info': () => jsonResponse(HEALTHY_SYSTEM_INFO),
      '/api/v1/simulation/control': () => jsonResponse({ status: 'SUCCESS' }),
    });
    const user = userEvent.setup();
    render(<SimulationView />);

    const input = screen.getByLabelText(/Speed factor/i);
    await user.clear(input);
    await user.type(input, '4');
    await user.click(screen.getByRole('button', { name: 'SET SPEED' }));

    expect(
      screen.getByText('Are you sure you want to execute: Set Speed Factor (4x)?'),
    ).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /CONFIRM & EXECUTE/ }));

    await waitFor(() => expect(mock.callsTo('/api/v1/simulation/control')).toHaveLength(1));
    expect(bodyOf(mock.callsTo('/api/v1/simulation/control')[0])).toEqual({
      action: 'SET_SPEED',
      speed_factor: 4,
    });
  });

  it('refuses a speed factor outside the permitted range without sending it', async () => {
    const mock = installFetchMock({
      '/api/v1/overview': () => jsonResponse(CONNECTED_TELEMETRY),
      '/api/v1/info': () => jsonResponse(HEALTHY_SYSTEM_INFO),
      '/api/v1/simulation/control': () => jsonResponse({ status: 'SUCCESS' }),
    });
    const user = userEvent.setup();
    render(<SimulationView />);

    const input = screen.getByLabelText(/Speed factor/i);
    await user.clear(input);
    await user.type(input, '500');
    await user.click(screen.getByRole('button', { name: 'SET SPEED' }));

    // The operator is told why, and no request is made.
    expect(
      screen.getByText(/A speed factor must be between 0 and 100; 500 was entered\./),
    ).toBeInTheDocument();
    expect(mock.callsTo('/api/v1/simulation/control')).toHaveLength(0);
  });
});

describe('Equipment Controller View', () => {
  it('asks for a confirmation before it trips the emergency stop', async () => {
    const user = userEvent.setup();
    render(<EquipmentControllerView />);

    await user.click(screen.getByRole('button', { name: /EMERGENCY STOP/ }));

    expect(screen.getByText('Confirm Equipment Control Action')).toBeInTheDocument();
    expect(
      screen.getByText('Are you sure you want to execute: Emergency Stop Trip?'),
    ).toBeInTheDocument();
    expect(screen.getByText(/Zero real equipment is targeted/i)).toBeInTheDocument();
  });

  it('names the startup sequence it is about to execute', async () => {
    const user = userEvent.setup();
    render(<EquipmentControllerView />);

    await user.click(screen.getByRole('button', { name: /STARTUP SEQUENCE/ }));

    expect(
      screen.getByText('Are you sure you want to execute: Execute Startup Sequence?'),
    ).toBeInTheDocument();
  });

  it('names the shutdown sequence it is about to execute', async () => {
    const user = userEvent.setup();
    render(<EquipmentControllerView />);

    await user.click(screen.getByRole('button', { name: /SHUTDOWN SEQUENCE/ }));

    expect(
      screen.getByText('Are you sure you want to execute: Execute Shutdown Sequence?'),
    ).toBeInTheDocument();
  });

  it('closes the confirmation once the operator confirms the action', async () => {
    const user = userEvent.setup();
    render(<EquipmentControllerView />);

    await user.click(screen.getByRole('button', { name: /STARTUP SEQUENCE/ }));
    await user.click(screen.getByRole('button', { name: /CONFIRM & EXECUTE/ }));

    expect(screen.queryByText('Confirm Equipment Control Action')).not.toBeInTheDocument();
  });

  it('closes the confirmation once the operator cancels the action', async () => {
    const user = userEvent.setup();
    render(<EquipmentControllerView />);

    await user.click(screen.getByRole('button', { name: /EMERGENCY STOP/ }));
    await user.click(screen.getByRole('button', { name: /CANCEL/ }));

    expect(screen.queryByText('Confirm Equipment Control Action')).not.toBeInTheDocument();
  });
});

describe('System Settings View', () => {
  it('states the safety invariants the platform runs under', () => {
    render(<SystemSettingsView />);

    const invariants = screen
      .getByText('Non-Negotiable Safety Invariants')
      .closest('.card') as HTMLElement;

    expect(invariants).toHaveTextContent('Application Mode: SIMULATION ONLY');
    expect(invariants).toHaveTextContent('Hardware Integration: DISABLED');
    expect(invariants).toHaveTextContent('External Modbus Writes: DISABLED');
    expect(invariants).toHaveTextContent('Automatic Device Discovery: DISABLED');
  });
});
