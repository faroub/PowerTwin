import React, { useState } from 'react';
import { Layout } from './components/Layout';
import { ViewId } from './components/Sidebar';
import { PlantOverviewView } from './views/PlantOverviewView';
import { SingleLineDiagramView } from './views/SingleLineDiagramView';
import { BatterySystemsView } from './views/BatterySystemsView';
import { BMSView } from './views/BMSView';
import { PCSView } from './views/PCSView';
import { TransformersSwitchgearView } from './views/TransformersSwitchgearView';
import { GridPOIView } from './views/GridPOIView';
import { EquipmentControllerView } from './views/EquipmentControllerView';
import { PPCView } from './views/PPCView';
import { EMSView } from './views/EMSView';
import { GridServicesView } from './views/GridServicesView';
import { AlarmsView } from './views/AlarmsView';
import { HistorianView } from './views/HistorianView';
import { WarrantyMetricsView } from './views/WarrantyMetricsView';
import { SimulationView } from './views/SimulationView';
import { ScenarioManagerView } from './views/ScenarioManagerView';
import { EquipmentLibraryView } from './views/EquipmentLibraryView';
import { PluginManagerView } from './views/PluginManagerView';
import { SystemSettingsView } from './views/SystemSettingsView';

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
      case 'bms':
        return <BMSView />;
      case 'pcs':
        return <PCSView />;
      case 'xfrm_swg':
        return <TransformersSwitchgearView />;
      case 'grid':
        return <GridPOIView />;
      case 'eq_controller':
        return <EquipmentControllerView />;
      case 'ppc':
        return <PPCView />;
      case 'ems':
        return <EMSView />;
      case 'grid_services':
        return <GridServicesView />;
      case 'alarms':
        return <AlarmsView />;
      case 'historian':
        return <HistorianView />;
      case 'warranty':
        return <WarrantyMetricsView />;
      case 'simulation':
        return <SimulationView />;
      case 'scenario':
        return <ScenarioManagerView />;
      case 'equipment_lib':
        return <EquipmentLibraryView />;
      case 'plugins':
        return <PluginManagerView />;
      case 'settings':
        return <SystemSettingsView />;
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
