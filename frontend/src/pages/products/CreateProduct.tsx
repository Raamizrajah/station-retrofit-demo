import React, { useState } from 'react';
import { getApiClient } from '@/api/client';
import type { ProductDto } from '@/api/models/ProductDto';

export const CreateProduct: React.FC = () => {
  const [name, setName] = useState('');
  const [sku, setSku] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [created, setCreated] = useState<ProductDto | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);

    try {
      const api = getApiClient();
      const product = await api.createProduct({ name, sku });
      setCreated(product);
      setName('');
      setSku('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div>
      <h2>Create Product</h2>

      <form onSubmit={handleSubmit} style={{ maxWidth: '400px' }}>
        <div style={{ marginBottom: '12px' }}>
          <label htmlFor="product-name" style={{ display: 'block', fontWeight: 600 }}>
            Name
          </label>
          <input
            id="product-name"
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            style={{ width: '100%', padding: '6px' }}
          />
        </div>

        <div style={{ marginBottom: '12px' }}>
          <label htmlFor="product-sku" style={{ display: 'block', fontWeight: 600 }}>
            SKU
          </label>
          <input
            id="product-sku"
            type="text"
            value={sku}
            onChange={(e) => setSku(e.target.value)}
            required
            style={{ width: '100%', padding: '6px' }}
          />
        </div>

        <button type="submit" disabled={submitting}>
          {submitting ? 'Creating…' : 'Create Product'}
        </button>
      </form>

      {error && <p style={{ color: 'red', marginTop: '12px' }}>Error: {error}</p>}
      {created && (
        <p style={{ color: 'green', marginTop: '12px' }}>
          Created product "{created.name}" (ID: {created.id})
        </p>
      )}
    </div>
  );
};
