import React, { useEffect, useState } from 'react';
import { getApiClient } from '@/api/client';
import { ProductStatus } from '@/api/models/ProductStatus';
import type { ProductDto } from '@/api/models/ProductDto';
import { StatusBadge } from '@/components/StatusBadge';

interface ProductDetailProps {
  productId: number;
}

export const ProductDetail: React.FC<ProductDetailProps> = ({ productId }) => {
  const [product, setProduct] = useState<ProductDto | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const api = getApiClient();
    api
      .getProduct(productId)
      .then(setProduct)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [productId]);

  if (loading) return <p>Loading product…</p>;
  if (error) return <p style={{ color: 'red' }}>Error: {error}</p>;
  if (!product) return <p>Product not found.</p>;

  const canEdit =
    product.status === ProductStatus.Draft ||
    product.status === ProductStatus.Active;

  const canArchive = product.status === ProductStatus.Active;
  const canDiscontinue =
    product.status === ProductStatus.Active ||
    product.status === ProductStatus.Archived;

  return (
    <div>
      <h2>{product.name}</h2>
      <StatusBadge status={product.status} />

      <dl style={{ marginTop: '16px' }}>
        <dt style={{ fontWeight: 600 }}>SKU</dt>
        <dd>{product.sku}</dd>

        <dt style={{ fontWeight: 600, marginTop: '8px' }}>Created</dt>
        <dd>{new Date(product.createdAt).toLocaleDateString()}</dd>

        <dt style={{ fontWeight: 600, marginTop: '8px' }}>Price entries</dt>
        <dd>{product.priceCount}</dd>
      </dl>

      <div style={{ marginTop: '16px', display: 'flex', gap: '8px' }}>
        {canEdit && <button>Edit</button>}
        {canArchive && <button>Archive</button>}
        {canDiscontinue && <button>Discontinue</button>}
        {product.status === ProductStatus.Draft && (
          <button style={{ backgroundColor: '#22c55e', color: '#fff' }}>
            Activate
          </button>
        )}
      </div>
    </div>
  );
};
