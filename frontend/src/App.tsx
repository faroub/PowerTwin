import React, { useState } from 'react';
import { Layout } from './components/Layout';
import { ViewId } from './components/Sidebar';
import { PlantOverviewView } from './views/PlantOverviewView';
import { SingleLineDiagramView } from './views/SingleLineDiagramView';
import { BatterySystemsView } from './views/BatterySystemsView';
import { PCSView } from './views/PCSView';
import { GridPOIView } from './views/GridPOIView';
import { EquipmentControllerView } from './views/EquipmentControllerView';
import { PPCView } from './views/PPCView';
import { EMSView } from './views/EMSView';
import { AlarmsView } from './views/AlarmsView';
import { HistorianView } from './views/HistorianView';
import { SimulationView } from './views/SimulationView';
import { ConfigurationView } from './views/ConfigurationView';
import { PluginManagerView } from './views/PluginManagerView';

export const App: React.FC = () => {
  const [currentView, setCurrentView] = useState<ViewId>('overview');

  const renderView = () => {
    switch (currentView) {
      case 'overview':
        return <PlantOverviewView />;
      case 'sld':
        return <SingleLineDiagramView />;
      case 'battery':
        return <BatterySystemsView />;
      case 'pcs':
        return <PCSView />;
      case 'grid':
        return <GridPOIView />;
      case 'eq_controller':
        return <EquipmentControllerView />;
      case 'ppc':
        return <PPCView />;
      case 'ems':
        return <EMSView />;
      case 'alarms':
        return <AlarmsView />;
      case 'historian':
        return <HistorianView />;
      case 'simulation':
        return <SimulationView />;
      case 'configuration':
        return <ConfigurationView />;
      case 'plugins':
        return <PluginManagerView />;
      default:
        return <PlantOverviewView />;
    }
  };

  return (
    <Layout currentView={currentView} onSelectView={setCurrentView}>
      {renderView()}
    </Layout>
  );
};
