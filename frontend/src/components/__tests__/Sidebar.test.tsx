import { render } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { Sidebar } from '../Sidebar';

const EXPECTED_VIEWS = [
  'Plant Overview',
  'Single-Line Diagram',
  'Battery Systems',
  'BMS',
  'PCS / Inverters',
  'Transformers & Switchgear',
  'Grid & POI',
  'Equipment Controller',
  'Power Plant Ctrl (PPC)',
  'EMS Dispatch',
  'Grid Services',
  'Alarms & Events',
  'Historian',
  'Warranty Metrics',
  'Simulation Control',
  'Scenario Manager',
  'Equipment Library',
  'Plugin Manager',
  'System Settings',
];

describe('Sidebar', () => {
  it('offers every view of the HMI', () => {
    const { container } = render(<Sidebar currentView="overview" onSelectView={vi.fn()} />);
    const sidebar = container.querySelector('.sidebar') as HTMLElement;

    for (const label of EXPECTED_VIEWS) {
      expect(sidebar).toHaveTextContent(label);
    }
    expect(sidebar.querySelectorAll('.nav-item')).toHaveLength(EXPECTED_VIEWS.length);
  });

  it('marks the active view', () => {
    const { container } = render(<Sidebar currentView="alarms" onSelectView={vi.fn()} />);
    const sidebar = container.querySelector('.sidebar') as HTMLElement;

    const active = sidebar.querySelectorAll('.nav-item.active');
    expect(active).toHaveLength(1);
    expect(active[0]).toHaveTextContent('Alarms & Events');
  });

  it('reports the view the operator selected', async () => {
    const onSelectView = vi.fn();
    const user = userEvent.setup();
    const { container } = render(<Sidebar currentView="overview" onSelectView={onSelectView} />);
    const sidebar = container.querySelector('.sidebar') as HTMLElement;

    await user.click(sidebar.querySelector('.nav-item:nth-child(3)') as HTMLElement);

    expect(onSelectView).toHaveBeenCalledTimes(1);
    expect(onSelectView).toHaveBeenCalledWith('battery');
  });
});
