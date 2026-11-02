import React, { useEffect, useState } from 'react';
import { getApiClient } from '@/api/client';
import { ProductStatus } from '@/api/models/ProductStatus';
import type { ProductDto } from '@/api/models/ProductDto';
import { StatusBadge } from '@/components/StatusBadge';

const ALL_STATUSES = [
  ProductStatus.Draft,
  ProductStatus.Active,
  ProductStatus.Archived,
  ProductStatus.Discontinued,
];

export const ProductList: React.FC = () => {
  const [products, setProducts] = useState<ProductDto[]>([]);
  const [filterStatus, setFilterStatus] = useState<ProductStatus | 'all'>('all');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const api = getApiClient();
    api
      .listProducts()
      .then(setProducts)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  const filtered =
    filterStatus === 'all'
      ? products
      : products.filter((p) => p.status === filterStatus);

  if (loading) return <p>Loading products…</p>;
  if (error) return <p style={{ color: 'red' }}>Error: {error}</p>;

  return (
    <div>
      <h2>Products</h2>

      <div style={{ marginBottom: '16px' }}>
        <label htmlFor="status-filter">Filter by status: </label>
        <select
          id="status-filter"
          value={filterStatus}
          onChange={(e) =>
            setFilterStatus(e.target.value as ProductStatus | 'all')
          }
        >
          <option value="all">All</option>
          {ALL_STATUSES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </div>

      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            <th style={{ textAlign: 'left', padding: '8px' }}>Name</th>
            <th style={{ textAlign: 'left', padding: '8px' }}>SKU</th>
            <th style={{ textAlign: 'left', padding: '8px' }}>Status</th>
            <th style={{ textAlign: 'right', padding: '8px' }}>Prices</th>
          </tr>
        </thead>
        <tbody>
          {filtered.map((product) => (
            <tr key={product.id} style={{ borderTop: '1px solid #e2e8f0' }}>
              <td style={{ padding: '8px' }}>{product.name}</td>
              <td style={{ padding: '8px' }}>{product.sku}</td>
              <td style={{ padding: '8px' }}>
                <StatusBadge status={product.status} />
              </td>
              <td style={{ padding: '8px', textAlign: 'right' }}>
                {product.priceCount}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {filtered.length === 0 && (
        <p style={{ color: '#94a3b8', textAlign: 'center', marginTop: '24px' }}>
          No products found.
        </p>
      )}
    </div>
  );
};
