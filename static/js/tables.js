window.FinFlowTables = (function () {
  const typeBadge = (type) => {
    const map = {
      credit: '<span class="badge badge-income">Credit</span>',
      debit: '<span class="badge badge-expense">Debit</span>',
    };
    return map[type] || `<span class="badge">${type}</span>`;
  };

  const accountTypeBadge = (type) => {
    const map = {
      bank: '<span class="badge" style="background:rgba(99,102,241,0.15);color:#818cf8">Bank</span>',
      cash: '<span class="badge badge-income">Cash</span>',
      credit_card: '<span class="badge badge-transfer">Credit Card</span>',
      wallet: '<span class="badge" style="background:rgba(34,211,238,0.15);color:#22d3ee">Wallet</span>',
    };
    return map[type] || `<span class="badge">${type}</span>`;
  };

  const formatAmount = (cell, type) => {
    const val = cell.getValue();
    const formatted = '₹' + Number(val).toLocaleString('en-IN', { minimumFractionDigits: 2 });
    if (type === 'debit') return `<span style="color:#f87171;font-weight:600">-${formatted}</span>`;
    if (type === 'credit') return `<span style="color:#34d399;font-weight:600">+${formatted}</span>`;
    const balance = Number(val);
    const color = balance >= 0 ? '#34d399' : '#f87171';
    return `<span style="color:${color};font-weight:600">${formatted}</span>`;
  };

  const baseConfig = {
    layout: "fitColumns", // Do not stretch columns
    responsiveLayout: "collapse",
    pagination: true,
    paginationSize: 15,
    paginationSizeSelector: [10, 15, 25, 50],
    movableColumns: false,
    resizableColumns: false,
    placeholder:
      '<div class="empty-state"><i class="bi bi-inbox"></i><p>No data found</p></div>',

    columnDefaults: {
      resizable: false,
      widthGrow: 0,
      widthShrink: 0,
    },
  };

  function initTransactions(containerId, data, searchInputId) {
    const el = document.getElementById(containerId);
    if (!el || typeof Tabulator === 'undefined') return;

    const table = new Tabulator(el, {
      ...baseConfig,
      data: data,
      initialSort: [{ column: 'date', dir: 'desc' }],
      columns: [
        {
          title: 'Date',
          field: 'date',
          sorter: 'date',
          width: 150,
          formatter: (cell) => {
            const d = new Date(cell.getValue());
            return d.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });
          },
        },
        {
          title: 'Type',
          field: 'type',
          width: 150,
          formatter: (cell) => typeBadge(cell.getValue()),
          headerFilter: 'list',
          headerFilterParams: { values: { '': 'All', credit: 'Credit', debit: 'Debit' } },
        },
        { title: 'Category', field: 'category', headerFilter: 'input' },
        { title: 'Merchant', field: 'merchant', headerFilter: 'input' },
        { title: 'Account', field: 'account', headerFilter: 'input' },
        {
          title: 'Amount',
          field: 'amount',
          hozAlign: 'right',
          sorter: 'number',
          formatter: (cell) => formatAmount(cell, cell.getData().type),
        },
        {
          title: 'Actions',
          field: 'edit_url',
          width: 150,
          hozAlign: 'center',
          headerSort: false,
          formatter: (cell) => {
            const row = cell.getData();
            return `
              <div class="d-inline-flex gap-2 align-items-center">
                <a href="${row.edit_url}" class="btn-icon" title="Edit transaction" aria-label="Edit transaction">
                  <i class="bi bi-pencil-square" aria-hidden="true"></i>
                </a>
                <a href="${row.delete_url}" class="btn-icon" title="Delete transaction" aria-label="Delete transaction" onclick="return confirm('Delete this transaction?')">
                  <i class="bi bi-trash" aria-hidden="true"></i>
                </a>
              </div>
            `;
          },
        },
      ],
    });

    const searchInput = document.getElementById(searchInputId);
    if (searchInput) {
      searchInput.addEventListener('input', () => {
        table.setFilter([
          [
            { field: 'category', type: 'like', value: searchInput.value },
            { field: 'merchant', type: 'like', value: searchInput.value },
            { field: 'account', type: 'like', value: searchInput.value },
            { field: 'description', type: 'like', value: searchInput.value },
          ],
        ]);
      });
    }

    return table;
  }

  function initAccounts(containerId, data, searchInputId) {
    const el = document.getElementById(containerId);
    if (!el || typeof Tabulator === 'undefined') return;

    const table = new Tabulator(el, {
      ...baseConfig,
      data: data,
      columns: [
        { title: 'Name', field: 'name', headerFilter: 'input', formatter: (cell) => `<strong>${cell.getValue()}</strong>` },
        {
          title: 'Type',
          field: 'type',
          width: 150,
          formatter: (cell) => accountTypeBadge(cell.getValue()),
          headerFilter: 'list',
          headerFilterParams: { values: { '': 'All', bank: 'Bank', cash: 'Cash', credit_card: 'Credit Card', wallet: 'Wallet' } },
        },
        {
          title: 'Opening',
          field: 'opening_balance',
          hozAlign: 'right',
          formatter: (cell) => '₹' + Number(cell.getValue()).toLocaleString('en-IN', { minimumFractionDigits: 2 }),
        },
        {
          title: 'Balance',
          field: 'current_balance',
          hozAlign: 'right',
          sorter: 'number',
          formatter: (cell) => formatAmount(cell),
        },
        { title: 'Created', field: 'created', width: 150 },
      ],
    });

    const searchInput = document.getElementById(searchInputId);
    if (searchInput) {
      searchInput.addEventListener('input', () => {
        table.setFilter('name', 'like', searchInput.value);
      });
    }

    return table;
  }

  function initReportTable(containerId, data, typeFilter = null) {
    const el = document.getElementById(containerId);
    if (!el || typeof Tabulator === 'undefined') return;

    let columns = [
      { title: 'Category',  field: 'name', headerFilter: 'input' },
      {
        title: 'Type',
        field: 'type',
        hozAlign: 'right',
        sorter: 'string',
        headerFilter: 'list',
        resiezable: false,
        headerFilterParams: { values: { '': 'All', income: 'Income', expense: 'Expense', credit: 'Credit' } },
        formatter: (cell) => {
          const type = cell.getValue();
          const color = type === 'expense' ? '#f87171' : type === 'income' ? '#34d399' : type === 'credit' ? '#34d399' : '#000';
          return `<span style="font-weight:900;color:${color}">${type}</span>`;
        },
      },
      {
        title: 'Amount',
        field: 'total',
        hozAlign: 'right',
        sorter: 'number',
        resiezable: false,
        formatter: (cell) => `<span style="font-weight:600">₹${Number(Math.abs(cell.getValue())).toLocaleString('en-IN', { minimumFractionDigits: 2 })}</span>`,
      },
      {
        title: 'Share',
        field: 'total',
        hozAlign: 'right',
        width: 150,
        resiezable: false,
        sorter: 'number',
        formatter: (cell) => {
          const total = data.reduce((s, r) => {
            if (r.type == cell.getData().type) s += r.total;
            return s;
          }, 0);
          const pct = total ? ((cell.getValue() / total) * 100).toFixed(1) : 0;
          return `<span style="color:#8b9cb8">${pct}%</span>`;
        },
      },
    ];
    console.log('Report table columns:', columns);
    let tabulator = new Tabulator(el, {
      ...baseConfig,
      pagination: false,
      initialSort: [{ column: 'type', dir: 'desc' }],
      data: data,
      columns: columns,
    });

    return tabulator;
  }

  return { initTransactions, initAccounts, initReportTable };
})();
