import React, { useEffect, useState } from 'react';
import { getApiClient } from '@/api/client';
import { PriceType } from '@/api/models/PriceType';
import type { PriceEntryDto } from '@/api/models/PriceEntryDto';
import { PriceTypeBadge } from '@/components/PriceTypeBadge';

const ALL_PRICE_TYPES = [PriceType.Retail, PriceType.Wholesale, PriceType.Partner];

export const PriceList: React.FC = () => {
  const [prices, setPrices] = useState<PriceEntryDto[]>([]);
  const [filterType, setFilterType] = useState<PriceType | 'all'>('all');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const api = getApiClient();
    api
      .listPrices()
      .then(setPrices)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  const filtered =
    filterType === 'all'
      ? prices
      : prices.filter((p) => p.type === filterType);

  if (loading) return <p>Loading prices…</p>;
  if (error) return <p style={{ color: 'red' }}>Error: {error}</p>;

  return (
    <div>
      <h2>Prices</h2>

      <div style={{ marginBottom: '16px' }}>
        <label htmlFor="type-filter">Filter by type: </label>
        <select
          id="type-filter"
          value={filterType}
          onChange={(e) => setFilterType(e.target.value as PriceType | 'all')}
        >
          <option value="all">All</option>
          {ALL_PRICE_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </div>

      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            <th style={{ textAlign: 'left', padding: '8px' }}>Product ID</th>
            <th style={{ textAlign: 'left', padding: '8px' }}>Type</th>
            <th style={{ textAlign: 'right', padding: '8px' }}>Amount</th>
            <th style={{ textAlign: 'left', padding: '8px' }}>Currency</th>
            <th style={{ textAlign: 'left', padding: '8px' }}>Valid From</th>
            <th style={{ textAlign: 'left', padding: '8px' }}>Valid To</th>
          </tr>
        </thead>
        <tbody>
          {filtered.map((price) => (
            <tr key={price.id} style={{ borderTop: '1px solid #e2e8f0' }}>
              <td style={{ padding: '8px' }}>{price.productId}</td>
              <td style={{ padding: '8px' }}>
                <PriceTypeBadge type={price.type} />
              </td>
              <td style={{ padding: '8px', textAlign: 'right' }}>
                {price.amount.toFixed(2)}
              </td>
              <td style={{ padding: '8px' }}>{price.currency}</td>
              <td style={{ padding: '8px' }}>
                {new Date(price.validFrom).toLocaleDateString()}
              </td>
              <td style={{ padding: '8px' }}>
                {price.validTo
                  ? new Date(price.validTo).toLocaleDateString()
                  : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {filtered.length === 0 && (
        <p style={{ color: '#94a3b8', textAlign: 'center', marginTop: '24px' }}>
          No prices found.
        </p>
      )}
    </div>
  );
};
