import { Select, MenuItem, Chip, Box } from '@mui/material'
import { BusinessOutlined as ClientIcon } from '@mui/icons-material'
import { useSelectedClient } from '../../contexts/SelectedClientContext'

const ALL_CLIENTS_VALUE = '__all__'

// Never rendered for role-client users (locked to their own org, no
// picker) -- App.tsx-level guard in MainLayout.tsx, not repeated here.
export default function ClientSelector() {
  const { clients, loading, selectedClient, setSelectedClient } = useSelectedClient()

  if (loading || clients.length === 0) return null

  return (
    <Select
      size="small"
      value={selectedClient?.name ?? ALL_CLIENTS_VALUE}
      onChange={e => {
        const value = e.target.value
        setSelectedClient(value === ALL_CLIENTS_VALUE ? null : clients.find(c => c.name === value) || null)
      }}
      displayEmpty
      startAdornment={<ClientIcon sx={{ fontSize: 18, mr: 0.5, opacity: 0.7 }} />}
      sx={{
        minWidth: 180,
        bgcolor: 'background.paper',
        '& .MuiSelect-select': { display: 'flex', alignItems: 'center', py: 0.75 },
      }}
    >
      <MenuItem value={ALL_CLIENTS_VALUE}>All Clients</MenuItem>
      {clients.map(c => (
        <MenuItem key={c.name} value={c.name}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, width: '100%' }}>
            <span>{c.name}</span>
            {c.has_edr && c.has_siem && <Chip size="small" label="EDR+SIEM" sx={{ ml: 'auto', height: 18, fontSize: '0.65rem' }} />}
          </Box>
        </MenuItem>
      ))}
    </Select>
  )
}
