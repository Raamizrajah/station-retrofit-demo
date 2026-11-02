import { ProductStatus } from './ProductStatus';

export interface UpdateProductRequest {
  name?: string;
  sku?: string;
  status?: ProductStatus;
}
