import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import '@fontsource/ibm-plex-sans/400.css';
import '@fontsource/ibm-plex-sans/500.css';
import '@fontsource/ibm-plex-sans/600.css';
import Studio from './app/page';
import TaskWorkspace, { CompanyWorkspace } from './app/TaskWorkspace';
import './styles.css';

const View = window.location.pathname.startsWith('/studio') ? Studio : window.location.pathname.startsWith('/company') ? CompanyWorkspace : TaskWorkspace;
createRoot(document.getElementById('root')!).render(<StrictMode><View /></StrictMode>);
