import React, { useState } from 'react';
import { getApiClient } from '@/api/client';
import { PriceType } from '@/api/models/PriceType';
import type { PriceEntryDto } from '@/api/models/PriceEntryDto';

const ALL_PRICE_TYPES = [PriceType.Retail, PriceType.Wholesale, PriceType.Partner];

export const CreatePrice: React.FC = () => {
  const [productId, setProductId] = useState('');
  const [currency, setCurrency] = useState('USD');
  const [amount, setAmount] = useState('');
  const [type, setType] = useState<PriceType>(PriceType.Retail);
  const [validFrom, setValidFrom] = useState('');
  const [validTo, setValidTo] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [created, setCreated] = useState<PriceEntryDto | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);

    try {
      const api = getApiClient();
      const price = await api.createPrice({
        productId: Number(productId),
        currency,
        amount: Number(amount),
        type,
        validFrom,
        validTo: validTo || undefined,
      });
      setCreated(price);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div>
      <h2>Create Price</h2>

      <form onSubmit={handleSubmit} style={{ maxWidth: '400px' }}>
        <div style={{ marginBottom: '12px' }}>
          <label htmlFor="price-product-id" style={{ display: 'block', fontWeight: 600 }}>
            Product ID
          </label>
          <input
            id="price-product-id"
            type="number"
            value={productId}
            onChange={(e) => setProductId(e.target.value)}
            required
            style={{ width: '100%', padding: '6px' }}
          />
        </div>

        <div style={{ marginBottom: '12px' }}>
          <label htmlFor="price-type" style={{ display: 'block', fontWeight: 600 }}>
            Type
          </label>
          <select
            id="price-type"
            value={type}
            onChange={(e) => setType(e.target.value as PriceType)}
            style={{ width: '100%', padding: '6px' }}
          >
            {ALL_PRICE_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>

        <div style={{ marginBottom: '12px' }}>
          <label htmlFor="price-amount" style={{ display: 'block', fontWeight: 600 }}>
            Amount
          </label>
          <input
            id="price-amount"
            type="number"
            step="0.01"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            required
            style={{ width: '100%', padding: '6px' }}
          />
        </div>

        <div style={{ marginBottom: '12px' }}>
          <label htmlFor="price-currency" style={{ display: 'block', fontWeight: 600 }}>
            Currency
          </label>
          <input
            id="price-currency"
            type="text"
            value={currency}
            onChange={(e) => setCurrency(e.target.value)}
            required
            style={{ width: '100%', padding: '6px' }}
          />
        </div>

        <div style={{ marginBottom: '12px' }}>
          <label htmlFor="price-valid-from" style={{ display: 'block', fontWeight: 600 }}>
            Valid From
          </label>
          <input
            id="price-valid-from"
            type="date"
            value={validFrom}
            onChange={(e) => setValidFrom(e.target.value)}
            required
            style={{ width: '100%', padding: '6px' }}
          />
        </div>

        <div style={{ marginBottom: '12px' }}>
          <label htmlFor="price-valid-to" style={{ display: 'block', fontWeight: 600 }}>
            Valid To (optional)
          </label>
          <input
            id="price-valid-to"
            type="date"
            value={validTo}
            onChange={(e) => setValidTo(e.target.value)}
            style={{ width: '100%', padding: '6px' }}
          />
        </div>

        <button type="submit" disabled={submitting}>
          {submitting ? 'Creating…' : 'Create Price'}
        </button>
      </form>

      {error && <p style={{ color: 'red', marginTop: '12px' }}>Error: {error}</p>}
      {created && (
        <p style={{ color: 'green', marginTop: '12px' }}>
          Created price entry (ID: {created.id})
        </p>
      )}
    </div>
  );
};
