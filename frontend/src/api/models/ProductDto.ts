import { ProductStatus } from './ProductStatus';

export interface ProductDto {
  id: number;
  name: string;
  sku: string;
  status: ProductStatus;
  createdAt: string;
  priceCount: number;
}
