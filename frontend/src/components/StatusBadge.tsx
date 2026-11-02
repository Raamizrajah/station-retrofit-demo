import React from 'react';
import { ProductStatus } from '@/api/models/ProductStatus';

interface StatusBadgeProps {
  status: ProductStatus;
}

const statusColors: Record<ProductStatus, { bg: string; text: string }> = {
  [ProductStatus.Draft]: { bg: '#e2e8f0', text: '#475569' },
  [ProductStatus.Active]: { bg: '#dcfce7', text: '#166534' },
  [ProductStatus.Archived]: { bg: '#fef3c7', text: '#92400e' },
  [ProductStatus.Discontinued]: { bg: '#fee2e2', text: '#991b1b' },
};

export const StatusBadge: React.FC<StatusBadgeProps> = ({ status }) => {
  const colors = statusColors[status] ?? { bg: '#f1f5f9', text: '#334155' };

  return (
    <span
      style={{
        display: 'inline-block',
        padding: '2px 8px',
        borderRadius: '12px',
        fontSize: '12px',
        fontWeight: 600,
        backgroundColor: colors.bg,
        color: colors.text,
      }}
    >
      {status}
    </span>
  );
};
